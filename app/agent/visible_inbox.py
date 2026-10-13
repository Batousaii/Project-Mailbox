"""Read an Inbox already mounted in the CURRENT classic Outlook session.

No Resolve(), GetSharedDefaultFolder(), new Outlook login or Exchange API calls.
Outlook itself may need its configured mail server for uncached shared items.
"""
import time
from .outlook import OutlookGateway
from .rules import TARGET_MAILBOX


def _find_attached_inbox(ns, target=TARGET_MAILBOX):
    """Return (folder, store) from an existing Outlook Store (no lookup by recipient)."""
    target_key = target.strip().casefold()
    matches = []
    for st in ns.Stores:
        name = str(st.DisplayName).strip().casefold()
        if name == target_key:
            matches.append(st)
    if len(matches) != 1:
        raise RuntimeError(
            'EE-Reliability is niet eenduidig zichtbaar als Outlook-mailbox ' 
            f'(gevonden: {len(matches)}). De agent vraagt geen extra servertoegang of rechten aan.'
        )
    store = matches[0]
    root = store.GetRootFolder()
    candidates = []
    for folder in root.Folders:
        name = str(folder.Name).strip().casefold()
        if name in ('inbox', 'postvak in'):
            candidates.append(folder)
    if len(candidates) == 1:
        return candidates[0], store
    # For other Outlook languages, use the default Inbox of the *mounted* store,
    # not recipient resolution on a remote mailbox.
    folder = store.GetDefaultFolder(6)
    if folder is None:
        raise RuntimeError('De reeds gekoppelde Outlook-mailbox heeft geen leesbare Inbox.')
    return folder, store


class VisibleInboxGateway(OutlookGateway):
    """Attach to running classic Outlook, without invoking Namespace.Logon()."""
    def __init__(self, app=None):
        self._com_initialized = False
        if app is None:
            try:
                from .outlook import pythoncom, win32com
                if pythoncom is None or win32com is None:
                    raise RuntimeError('pywin32 voor Outlook COM ontbreekt')
                pythoncom.CoInitialize()
                self._com_initialized = True
                app = win32com.client.GetActiveObject('Outlook.Application')
            except Exception as exc:
                self.close()
                raise RuntimeError(
                    'De bestaande klassieke Outlook-sessie is niet bereikbaar. ' 
                    'Open eerst de reeds geconfigureerde EE-Reliability Inbox in Outlook. ' 
                    f'Originele fout: {exc}'
                ) from exc
        self.app = app
        try:
            self.ns = app.GetNamespace('MAPI')
            self.inbox, self.store = _find_attached_inbox(self.ns)
            self.store_id = str(self.store.StoreID)
        except Exception:
            self.close()
            raise

    def close(self):
        if self._com_initialized:
            from .outlook import pythoncom
            self.app = self.ns = self.inbox = self.store = None
            pythoncom.CoUninitialize()
            self._com_initialized = False


def open_visible_inbox(retries=3, wait_seconds=3, factory=VisibleInboxGateway):
    """Retry temporary Outlook COM failures; no account changes or send actions."""
    last_error = None
    for attempt in range(1, retries+1):
        gateway = None
        try:
            gateway = factory()
            # A complete snapshot proves the mailbox can actually be read.
            snapshot = gateway.snapshot()
            if not snapshot:
                raise RuntimeError('De gemounte EE-Reliability Inbox toont 0 MailItems. Omdat eerder mail aanwezig was, wordt dit niet stilzwijgend als een volledige scan beschouwd.')
            print('LIVE EE-Reliability Inbox: ' + str(len(snapshot)) + ' zichtbare MailItems; ' 
                  'geen server-resolve en geen verzending.', flush=True)
            return gateway, snapshot
        except Exception as exc:
            if gateway is not None and hasattr(gateway, 'close'):
                gateway.close()
            last_error = exc
            print('Outlook Inbox poging ' + str(attempt) + '/' + str(retries) + ' mislukt: ' + str(exc), flush=True)
            if attempt < retries:
                time.sleep(wait_seconds)
    raise RuntimeError(
        'De actuele EE-Reliability Inbox kon niet via de bestaande Outlook-sessie ' 
        'worden gelezen. Er is GEEN aparte Exchange-aanmelding geprobeerd en niets ' 
        'verzonden of gewijzigd. Outlook kan zijn eigen Exchange-verbinding nodig ' 
        'hebben wanneer gedeelde mail niet lokaal gecachet is. Laat de Inbox in ' 
        f'klassieke Outlook volledig openen en controleer de verbinding. Laatste fout: {last_error}'
    ) from last_error
