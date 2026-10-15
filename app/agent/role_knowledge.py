"""Small, local domain graph. Retrieval supplies context; it never authorizes actions."""
import json
import re
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=1)
def load():
    data=json.loads(Path(__file__).with_name('role_knowledge.json').read_text(encoding='utf-8'))
    ids={c['id'] for c in data['concepts']}
    if len(ids)!=len(data['concepts']):
        raise ValueError('Duplicate knowledge concept')
    for c in data['concepts']:
        if not c['aliases'] or not set(c['related']) <= ids:
            raise ValueError('Invalid knowledge aliases/relations')
    return data


def matches(text):
    text=text or ''
    found=[]
    for concept in load()['concepts']:
        aliases=[alias for alias in concept['aliases']
                 if re.search(r'(?<!\w)'+re.escape(alias)+r'(?!\w)',text,re.I)]
        if aliases:
            found.append((concept,aliases))
    return found


def supports_plan(text):
    return any(c['plan_object'] for c,_ in matches(text))


def context_for(subject, latest, max_chars=4200):
    data=load()
    direct=matches((subject or '')+'\n'+(latest or ''))
    concepts=[c for c,_ in direct]
    wanted={ref for c in concepts for ref in c['related']}
    concepts += [c for c in data['concepts'] if c['id'] in wanted and c not in concepts]
    head='ROLKENNIS '+data['version']+' — '+data['role']+'\n'+'\n'.join(data['boundaries'])
    lines=[head]
    for c in concepts:
        line=c['id']+' ('+c['label']+'): '+c['meaning']+' Relaties: '+', '.join(c['related'])
        if len('\n'.join(lines))+len(line)+1>max_chars:
            break
        lines.append(line)
    return '\n'.join(lines)
