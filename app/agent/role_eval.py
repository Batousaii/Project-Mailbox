"""Real local-model acceptance, synthetic mail only; never imports Outlook or sends."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from . import ai
from .rules import MODEL,split_latest_message
from .role_knowledge import load

CASES=[
    ('item_interval','Correctie maintenance item tekst','Maintenance item zonder periodiciteit, denk 6M.',False,'MODIFY_PLAN'),
    ('plan_rule','Planwijziging','Gelieve PO plan 4321 aan te passen; regel 3 mag eruit.',False,'MODIFY_PLAN'),
    ('tasklist','Onderhoudstaaklijst','Wijzig de onderhoudstaaklijst voor pomp P-EXAMPLE: voeg de lagerinspectie toe.',False,'MODIFY_PLAN'),
    ('strategy','Maintenance strategy','Please change the maintenance strategy package from 6M to 12M.',False,'MODIFY_PLAN'),
    ('new_plan','Nieuw plan','Maak een nieuw inspectieplan voor de loopbrug.',False,'CREATE_PLAN'),
    ('ei_spare','Reserveonderdeel','Graag een reserve druktransmitter voor meetlus PT-EXAMPLE bestellen.',True,'NONE'),
    ('ei_bom','Stuklijst','Voeg de PLC-voedingsmodule toe aan de elektrische stuklijst.',True,'NONE'),
    ('mechanical','Reserveonderdeel','Graag een lager voor de tandwielkast bestellen voor magazijnvoorraad.',False,'NONE'),
    ('purchase_order','Purchase order','Please correct the delivery address on purchase order PO-EXAMPLE.',False,'NONE'),
    ('completion','Onderhoud','Het inspectieplan is aangepast. Het werk is afgerond.',False,'NONE'),
    ('quote_only','RE: Inspectieplan','Bedankt, ter info. Geen nieuwe actie.\n\nFrom: A\nSent: gisteren\nMaak een nieuw inspectieplan.',False,'NONE'),
    ('future_other','Planning leverancier','Zodra de leverancier de slijtagemeting heeft afgerond, kan het leveranciersteam later een onderhoudsplan opmaken. Er is nu geen actie voor EE-Reliability of Hamza.',False,'NONE'),
    ('assigned_preparation','Voorbereiding onderhoud','Hamza, graag nu een nieuw onderhoudsplan voorbereiden voor de pomp. Uitvoering volgt pas na de slijtagemeting.',False,'CREATE_PLAN'),
    ('completion_and_new','Nieuwe actie','De inspectie is uitgevoerd. Graag de sensor opnieuw kalibreren.',True,'NONE'),
]


def signature():
    data={'knowledge':load(),'prompt':ai.SYSTEM_PROMPT,'cases':CASES,'model':MODEL,
          'classifier':Path(ai.__file__).read_text(encoding='utf-8'),
          'retrieval':Path(__file__).with_name('role_knowledge.py').read_text(encoding='utf-8'),
          'evaluation':Path(__file__).read_text(encoding='utf-8'),
          'rules':Path(__file__).with_name('rules.py').read_text(encoding='utf-8')}
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()


def model_digest():
    tags=ai.request_json('/api/tags',timeout=12)
    for model in tags.get('models',[]):
        if model.get('name','').lower() in (MODEL,MODEL+':latest') and model.get('digest'):
            return model['digest']
    raise RuntimeError('Modeldigest niet beschikbaar; inhoudelijke test kan niet worden hergebruikt')


def run(output):
    fingerprint=signature();digest=model_digest()
    try:
        previous=json.loads(output.read_text(encoding='utf-8'))
    except (OSError,ValueError):
        previous={}
    if (previous.get('signature')==fingerprint and previous.get('model_digest')==digest
            and previous.get('passed')==len(CASES) and previous.get('failed')==0):
        print('Eerder geslaagde inhoudelijke test hergebruikt: identieke code, kennis, testset en model.',flush=True)
        return 0
    rows=[]
    try:
        for index,(key,subject,body,ei,plan) in enumerate(CASES,1):
            print(f'AI-ROLTEST {index}/{len(CASES)}: {key} ...',flush=True)
            try:
                latest,history=split_latest_message(body)
                result=ai.classify(subject,latest,history)
                passed=(result.ei_relevant==ei and result.plan_type==plan and
                        result.work_requested==(plan!='NONE') and not result.review_required)
                rows.append(dict(id=key,passed=passed,decision=result.__dict__))
                print('PASS' if passed else 'FAIL: '+result.reason,flush=True)
            except Exception as exc:
                rows.append(dict(id=key,passed=False,error=str(exc)))
                print('FAIL: '+str(exc),flush=True)
    finally:
        try:ai.release_model()
        except Exception:pass
    report=dict(version=load()['version'],model=MODEL,model_digest=digest,signature=fingerprint,
                completed_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                passed=sum(r['passed'] for r in rows),failed=sum(not r['passed'] for r in rows),results=rows)
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_suffix('.tmp');temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(output)
    print(f"Inhoudelijke AI-roltest: {report['passed']} geslaagd, {report['failed']} mislukt. Rapport: {output}",flush=True)
    return 0 if report['failed']==0 and len(rows)==len(CASES) else 2


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=Path('role-evaluation.json'));args=p.parse_args()
    ai.health(check_generation=False)
    return run(args.output)

if __name__=='__main__':
    raise SystemExit(main())
