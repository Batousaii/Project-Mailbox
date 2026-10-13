import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

from agent.visible_inbox import _find_attached_inbox, VisibleInboxGateway, open_visible_inbox
from agent.reconcile import audit_full
from agent.state import State


class Store:
    DisplayName = 'EE-Reliability'
    StoreID = 'local-mounted-store'
    def __init__(self):
        self.inbox = SimpleNamespace(Name='Inbox', EntryID='FOLDER', Items=None)
        self.folder = SimpleNamespace(Folders=[self.inbox])
        self.calls = []
    def GetRootFolder(self):
        self.calls.append('root')
        return self.folder
    def GetDefaultFolder(self, folder_id):
        self.calls.append(('default', folder_id))
        return self.inbox


class VisibleInboxTests(unittest.TestCase):
    def test_uses_only_visible_store_no_recipient_resolve_or_logon(self):
        store = Store()
        ns = SimpleNamespace(Stores=[store])
        app = SimpleNamespace(GetNamespace=lambda name: ns)
        with redirect_stdout(io.StringIO()):
            gw = VisibleInboxGateway(app=app)
        self.assertIs(gw.inbox, store.inbox)
        self.assertEqual(store.calls, ['root'])
        self.assertEqual(gw.store_id,'local-mounted-store')

    def test_missing_mount_must_not_do_server_lookup(self):
        with self.assertRaisesRegex(RuntimeError,'niet eenduidig zichtbaar'):
            _find_attached_inbox(SimpleNamespace(Stores=[]))

    def test_retry_temporary_com_error_without_login(self):
        class Snapshot:
            def snapshot(self):
                return [{'entry_id':'x'}]
        calls = []
        def build():
            calls.append(1)
            if len(calls) == 1:
                raise OSError('OLE error 0xa934011d')
            return Snapshot()
        with redirect_stdout(io.StringIO()):
            gw, rows = open_visible_inbox(retries=2,wait_seconds=0,factory=build)
        self.assertEqual(len(rows),1)
        self.assertEqual(len(calls),2)

    def test_inaccessible_mounted_inbox_fails_without_claiming_success(self):
        def fail():
            raise OSError('OLE error 0xa934011d')
        with redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'niet via de bestaande Outlook-sessie'):
                open_visible_inbox(retries=2,wait_seconds=0,factory=fail)

    def test_reusing_snapshot_no_second_lookups_or_sends(self):
        class ReadOnlyGateway:
            def snapshot(self):
                raise AssertionError('No second Inbox snapshot required')
            def detail(self, msg):
                return {'body':'Ter informatie', 'headers':'', 'categories':'', 'message_class':'IPM.Note'}
            def forward(self, *args):
                raise AssertionError('No forwards from audit')
        from agent.rules import Decision
        with tempfile.TemporaryDirectory() as td:
            state = State(Path(td)); state.set_setting('baseline_completed','1'); state.close()
            row = {'entry_id':'id1','received':'2026-10-12T12:00:00+00:00','subject':'Info',
                   'categories':'', 'conversation_id':'c1', 'store_id':'local-mounted-store'}
            with redirect_stdout(io.StringIO()):
                report = audit_full(td, ReadOnlyGateway(), lambda *_: Decision(), snapshot=[row])
            self.assertEqual(report['snapshot_inbox_count'],1)
            self.assertEqual(report['historical_mail_forwarded_by_this_audit'],0)


if __name__ == '__main__': unittest.main()
