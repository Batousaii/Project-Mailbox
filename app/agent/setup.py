"""Installer-only model preparation, before baseline/startup. No mailbox actions."""
from . import ai
from .rules import MODEL


def prepare_model():
    ai.ensure_server()
    tags=ai.request_json('/api/tags',timeout=12)
    if MODEL not in {m.get('name','').lower() for m in tags.get('models',[])}:
        print('Ontbrekend model downloaden: '+MODEL+' (kan meerdere GB zijn)',flush=True)
        ai.request_json('/api/pull',{'model':MODEL,'stream':False},timeout=1800)
    print(ai.health(check_generation=True),flush=True)

if __name__=='__main__':
    prepare_model()
