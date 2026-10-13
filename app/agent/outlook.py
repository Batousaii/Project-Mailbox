"""Classic Outlook COM access: read source Inbox, send forwards, never alter source items."""
import datetime as dt
from .rules import TARGET_MAILBOX, canonical_subject

try:
    import pythoncom
    import win32com.client
except ImportError:
    pythoncom = None
    win32com = None


class OutlookGateway:
    def __init__(self):
        if pythoncom is None or win32com is None:
            raise RuntimeError('pywin32 / pythoncom ontbreekt')
        pythoncom.CoInitialize()
        self.app = win32com.client.Dispatch('Outlook.Application')
        self.ns = self.app.GetNamespace('MAPI')
        self.ns.Logon('', '', False, False)
        self.inbox, self.store = self._find_shared_inbox()
        self.store_id = str(self.store.StoreID) if self.store is not None else str(self.inbox.StoreID)

    def _find_shared_inbox(self):
        matches = []
        target = TARGET_MAILBOX.casefold()
        for store in self.ns.Stores:
            display = str(store.DisplayName).strip().casefold()
            if display == target or display.startswith(target + ' -'):
                matches.append(store)
        if len(matches) > 1:
            raise RuntimeError('Meerdere mailboxstores met de naam EE-Reliability; stop wegens ambiguiteit')
        if len(matches) == 1:
            st = matches[0]
            return st.GetDefaultFolder(6), st
        # Delegate access without a mounted Store.
        recipient = self.ns.CreateRecipient(TARGET_MAILBOX)
        if not recipient.Resolve():
            raise RuntimeError('Gedeelde Outlook-mailbox EE-Reliability niet gevonden/opgelost')
        folder = self.ns.GetSharedDefaultFolder(recipient, 6)
        return folder, folder.Store

    def mailbox_info(self):
        return {'mailbox': str(self.inbox.Name), 'store': str(self.store.DisplayName),
                'entry_id': str(self.inbox.EntryID), 'store_id': self.store_id}

    @staticmethod
    def received(item):
        try:
            stamp = item.ReceivedTime
            if stamp.tzinfo is None:
                stamp = stamp.astimezone()
            return stamp.astimezone(dt.timezone.utc).isoformat(timespec='seconds')
        except Exception:
            return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')

    def snapshot(self):
        """Stable sequential GetFirst/GetNext; metadata only, no Body read."""
        items = self.inbox.Items
        snapshot = []
        itm = items.GetFirst()
        while itm is not None:
            try:
                if int(itm.Class) == 43:  # olMail
                    entry = str(itm.EntryID or '')
                    if entry:
                        subject = str(itm.Subject or '')
                        try:
                            conv = str(itm.ConversationID or '')
                        except Exception:
                            conv = ''
                        snapshot.append({
                            'entry_id': entry, 'store_id': self.store_id,
                            'conversation_id': conv,
                            'group_fallback': 'subject:' + canonical_subject(subject),
                            'received': self.received(itm), 'subject': subject,
                            'categories': str(itm.Categories or ''),
                            'message_class': str(itm.MessageClass or ''),
                        })
            except Exception as exc:
                # Never silently omit an existing Inbox item during the historical baseline.
                # An incomplete baseline could later misclassify old mail as newly arrived.
                raise RuntimeError('Outlook Inbox snapshot incomplete; safe retry required: ' + str(exc)) from exc
            itm = items.GetNext()
        return snapshot

    def get_item(self, entry_id, store_id=''):
        try:
            return self.ns.GetItemFromID(entry_id, store_id or self.store_id)
        except Exception:
            return self.ns.GetItemFromID(entry_id)

    def detail(self, msg):
        item = self.get_item(msg['entry_id'], msg['store_id'])
        if int(item.Class) != 43:
            raise RuntimeError('Geen Outlook MailItem')
        headers = ''
        try:
            headers = str(item.PropertyAccessor.GetProperty('http://schemas.microsoft.com/mapi/proptag/0x007D001E'))
        except Exception:
            pass
        return {'body': str(item.Body or ''), 'headers': headers,
                'message_class': str(item.MessageClass or ''),
                'categories': str(item.Categories or '')}

    def forward(self, entry_id, store_id, to_address, token):
        item = self.get_item(entry_id, store_id)
        if int(item.Class) != 43:
            raise RuntimeError('Outlook-item is geen e-mail')
        fwd = item.Forward()
        fwd.To = to_address
        # Traceable marker for post-crash reconciliation (visible in forwarded copy).
        fwd.Body = '[EE-Reliability referentie: ' + token + ']\r\n\r\n' + str(fwd.Body)
        try:
            p = fwd.UserProperties.Add('EEReliabilitySendToken', 1)
            p.Value = token
        except Exception:
            pass
        fwd.Send()

    def sent_copy_exists(self, token, max_items=1200):
        folders = []
        try:
            folders.append(self.ns.GetDefaultFolder(5))  # olFolderSentMail
        except Exception:
            pass
        try:
            f = self.store.GetDefaultFolder(5)
            if not any(str(x.EntryID) == str(f.EntryID) for x in folders):
                folders.append(f)
        except Exception:
            pass
        marker = '[EE-Reliability referentie: ' + token + ']'
        for folder in folders:
            items = folder.Items
            try:
                items.Sort('[SentOn]', True)
            except Exception:
                pass
            itm = items.GetFirst()
            inspected = 0
            while itm is not None and inspected < max_items:
                inspected += 1
                try:
                    if int(itm.Class) == 43:
                        try:
                            prop = itm.UserProperties.Find('EEReliabilitySendToken')
                            if prop is not None and str(prop.Value) == token:
                                return True
                        except Exception:
                            pass
                        if marker in str(itm.Body or '')[:500]:
                            return True
                except Exception:
                    pass
                itm = items.GetNext()
        return False
