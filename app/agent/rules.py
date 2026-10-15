"""Conservative, evidence-grounded EE-Reliability mail forwarding policy v1.5.

The LLM interprets the message; these checks prevent plausible-sounding but
ungrounded approvals. A self-reported confidence is not a calibrated probability.
"""
import json
import re
import unicodedata
from dataclasses import dataclass, replace

TARGET_MAILBOX = 'EE-Reliability'
RECIPIENT = 'hamza.elmakhtari@kuraray.com'
MODEL = 'qwen3:4b'
MIN_CONFIDENCE_EXCLUSIVE = 0.80
POLICY_VERSION = '1.7.2'

_QUOTE_LINES = [
    re.compile(r'^\s*-{2,}\s*(?:original message|oorspronkelijk bericht)\s*-{2,}', re.I),
    re.compile(r'^\s*(?:from|van|sent|verzonden|to|aan|subject|onderwerp):\s+', re.I),
    re.compile(r'^\s*(?:on .{5,160} wrote:|op .{5,160} schreef:)', re.I),
    re.compile(r'^\s*_{8,}\s*$'),
]
_AUTOREPLY = re.compile(
    r'\b(?:automatic reply|automatisch antwoord|auto.?reply|out of office|afwezigheidsassistent|'
    r'undeliverable|delivery failure|delivery status notification|non.delivery report|'
    r'onbestelbaar|delivery has failed|mail delivery subsystem)\b', re.I)
# Evidence guardrails, not the primary classifier. Only explicit E&I context can
# authorize an E&I-only forward; implicit or ambiguous cases go to manual review.
_EI_SIGNAL = re.compile(
    r'\b(?:e\s*&\s*i|electrical|elektrisch\w*|electriciteit|electrician|instrument\w*|'
    r'automatis\w*|automation|plc|dcs|scada|transmitter\w*|sensor\w*|'
    r'kalibr\w*|calibr\w*|thermokoppel\w*|thermocouple\w*|'
    r'pressure\s+(?:switch|transmitter)|druk\s*(?:schakelaar|transmitter)|'
    r'temperatuur\s*(?:sensor|transmitter|meting)|level\s*(?:sensor|transmitter)|'
    r'meetlus|meetkring|loop\s*check|cable|bekabeling|kabel\w*|'
    r'elektromotor\w*|frequentieomvormer\w*|inverter\w*|vfd|'
    r'sturing\w*|besturing\w*|actuator\w*|regelk\w*|control\s+valve|'
    r'proximity\w*|encoder\w*|switchgear|schakelkast\w*|'
    r'flow\s*meter|flowmeter\w*|debietmeter\w*|solenoid\w*|magneetventiel\w*)\b', re.I)
_MECHANICAL_SIGNAL = re.compile(
    r'\b(?:lager\w*|bearing\w*|gearbox\w*|\bgbx\b|tandwielkast\w*|'
    r'schroef\w*|schroeven|bolt\w*|gasket\w*|pakking\w*|'
    r'cutter\w*|bedmes\w*|meshouder\w*|scraper\w*|schraper\w*|'
    r'die.?plate\w*|stoomtrap\w*|steam\s*trap|piping|leiding\w*|'
    r'flens\w*|flange\w*|veer\w*|spring\w*|beltfeeder|'
    r'vlotter\w*|flexibel\w*|hose\w*|slang\w*)\b', re.I)
_PLAN_ACTION = re.compile(
    r'\b(?:aanvraag|aanvragen|aangevraagd|opzetten|aanmaken|maak|maken|'
    r'aan\s+te\s+passen|mag\s+eruit|correct\w*|corrig\w*|wijzig\w*|aanpas\w*|bijwerk\w*|uitbreid\w*|uitbreiden|toevoeg\w*|'
    r'stop\w*|afschaf\w*|verwijder\w*|update\w*|create\w*|set\s+up|'
    r'please|could\s+you|can\s+you|modify\w*|amend\w*|change\w*|'
    r'revise\w*|extend\w*)\b',re.I)
_PLAN_SIGNAL = re.compile(
    r'\b(?:inspectie\s*plan\w*|inspectieplannen|inspection\s+plan\w*|'
    r'po\s*[- ]\s*plan\w*|onderhouds\s*plan\w*|maintenance\s+plan\w*|maintenance\s+item\w*|onderhoudsitem\w*|'
    r'preventive\s+maintenance\s+plan\w*|preventief\s+onderhouds\s*plan\w*)\b',re.I)


def has_hamza_category(categories):
    return any(x.strip().casefold() == 'hamza' for x in re.split(r'[,;]', categories or ''))


def is_system_message(subject, message_class='', headers='', body=''):
    mc = (message_class or '').casefold()
    if mc.startswith(('report.', 'ipm.note.rules.oof')) or 'ndr' in mc:
        return True
    if _AUTOREPLY.search(subject or ''):
        return True
    if re.search(r'(?im)^auto-submitted:\s*(?!no\b)([^\r\n]+)', headers or ''):
        return True
    if re.search(r'(?im)^x-autoreply:\s*yes', headers or ''):
        return True
    return not (body or '').strip()


def split_latest_message(body):
    lines = (body or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    cut = len(lines)
    for i, line in enumerate(lines):
        if i >= 1 and any(p.match(line) for p in _QUOTE_LINES):
            if re.match(r'^\s*(from|van):\s+', line, re.I):
                window = '\n'.join(lines[i:i + 8])
                if not re.search(r'(?im)^\s*(sent|verzonden|to|aan|subject|onderwerp):', window):
                    continue
            cut = i
            break
    return '\n'.join(lines[:cut]).strip()[:12000], '\n'.join(lines[cut:]).strip()[:3500]


def canonical_subject(subject):
    value = (subject or '').strip()
    for _ in range(8):
        updated = re.sub(r'^(?:\s*(?:re|aw|fw|fwd|sv)\s*:\s*)', '', value, flags=re.I)
        if value == updated:
            break
        value = updated
    return re.sub(r'\s+', ' ', value).casefold()


def _normalize(t):
    t = unicodedata.normalize('NFKC', t or '').casefold()
    t = re.sub(r'[\u201c\u201d\u2018\u2019"\']', '', t)
    return ' '.join(t.split())


@dataclass(frozen=True)
class Decision:
    ei_relevant: bool = False
    plan_type: str = 'NONE'
    work_requested: bool = False
    confidence: float = 0.0
    reason: str = ''
    review_required: bool = False
    plan_target: str = ''
    domain: str = 'UNCLEAR'
    evidence: str = ''
    message_intent: str = 'UNSPECIFIED'
    intent_evidence: str = ''


_COMPLETED = re.compile(r'\b(?:is|zijn|werd|werden|hebben|heb|has been|have been|was|were)\s+(?:(?:reeds|al|inmiddels|succesvol|successfully|already)\s+)*(?:uitgevoerd|afgerond|voltooid|aangemaakt|aangepast|bijgewerkt|completed|performed|finished|created|updated)\b|\b(?:werk|werkzaamheden|job|work|task)\s+(?:is\s+)?(?:klaar|gereed|done)\b', re.I)
_OPEN_ACTION = re.compile(r'\b(?:graag|gelieve|please|kun\s+je|kan\s+je|kunt\s+u|can\s+you|could\s+you|moet\w*|nog|niet|not|still|pending|openstaand\w*|verzoek\w*|vraag\w*|request\w*)\b|\?', re.I)
_DIRECT_ACTION = re.compile(r'(?:^|[.!?;,\n])\s*(?:maak|pas|wijzig|voeg|controleer|kalibreer|bestel|vervang|stuur|create|modify|update|check|calibrate|order|replace|send)\b', re.I)


def completed_notice(latest):
    """Cheap, deliberately narrow completion gate; ambiguity goes to the model."""
    text = (latest or '').strip()
    if len(text) <= 800 and _COMPLETED.search(text) and not _OPEN_ACTION.search(text) and not _DIRECT_ACTION.search(text):
        return Decision(confidence=1.0, reason='Uitgevoerd werk; geen nieuw verzoek in nieuwste boodschap',
                        message_intent='COMPLETED', intent_evidence=text[:350])
    return None


_PLAN_CHANGE_DETAIL = re.compile(r'\b(?:zonder|missing|incorrect|wrong|ontbrekende)\s+(?:de\s+)?(?:periodiciteit|periodicity|interval|frequentie)|\b(?:periodiciteit|interval|frequentie)\s+ontbreekt\b', re.I)


def plan_review_candidate(subject, latest):
    """Request a second semantic review, never authorize work or sending by keywords."""
    if completed_notice(latest):
        return False
    scope = (subject or '') + '\n' + (latest or '')
    return bool(_PLAN_SIGNAL.search(scope) and
                (_PLAN_ACTION.search(latest or '') or _PLAN_CHANGE_DETAIL.search(latest or '') or
                 re.search(r'\b(?:correctie|correction|aanpassing|wijziging)\b', subject or '', re.I)))


def decode_classification(raw):
    try:
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict):
            raise ValueError('Expected JSON object')
        ei = raw.get('ei_relevant')
        work = raw.get('work_requested')
        subtype = str(raw.get('plan_type', 'NONE')).upper()
        domain = str(raw.get('domain','UNCLEAR')).upper()
        conf = float(raw.get('confidence', 0))
        if not isinstance(ei, bool) or not isinstance(work, bool):
            raise ValueError('Missing boolean attributes')
        if subtype not in ('NONE', 'CREATE_PLAN', 'MODIFY_PLAN'):
            raise ValueError('Unknown plan subtype')
        if domain not in ('EI', 'PLAN', 'MECHANICAL', 'OTHER', 'UNCLEAR'):
            raise ValueError('Invalid domain')
        if not 0 <= conf <= 1:
            raise ValueError('Invalid confidence')
        if work != (subtype != 'NONE'):
            raise ValueError('Plan subtype/work request inconsistent')
        evidence = str(raw.get('evidence', '')).strip()[:350]
        intent = str(raw.get('message_intent', 'UNSPECIFIED')).upper()
        if intent not in ('UNSPECIFIED', 'ACTION_REQUIRED', 'COMPLETED', 'STATUS_ONLY', 'UNCLEAR'):
            raise ValueError('Unknown message intent')
        intent_evidence = str(raw.get('intent_evidence', '')).strip()[:350]
        review = bool(raw.get('review_required', False)) or conf <= MIN_CONFIDENCE_EXCLUSIVE
        if (ei or work) and not evidence:
            review = True
        if work and domain != 'PLAN':
            review = True
        if ei and not work and domain != 'EI':
            review = True
        return Decision(ei, subtype, work, conf, str(raw.get('reason', '')).strip()[:800],
                        review, str(raw.get('plan_target', '')).strip()[:180], domain, evidence,
                        intent, intent_evidence)
    except (ValueError, TypeError, KeyError) as exc:
        return Decision(reason=f'REVIEW_REQUIRED: ongeldig modelantwoord ({exc})', review_required=True)


def ground_decision(cls, subject, latest):
    """Validate claimed evidence belongs to the NEW text, not quote history."""
    if cls.message_intent in ('COMPLETED', 'STATUS_ONLY'):
        if (cls.review_required or cls.confidence <= MIN_CONFIDENCE_EXCLUSIVE or
                len(cls.intent_evidence) < 6 or _normalize(cls.intent_evidence) not in _normalize(latest) or
                cls.work_requested or cls.ei_relevant or _DIRECT_ACTION.search(latest)):
            return replace(cls, message_intent='UNCLEAR', review_required=True,
                           reason='REVIEW_REQUIRED: status/afronding niet eenduidig onderbouwd')
        return cls
    if cls.review_required or (not cls.ei_relevant and not cls.work_requested):
        return cls
    if not latest.strip() or len(cls.evidence.strip()) < 6 or _normalize(cls.evidence) not in _normalize(latest):
        return replace(cls, review_required=True,
                       reason='REVIEW_REQUIRED: modelbewijs niet letterlijk in nieuwste bericht: ' + cls.reason)
    scope = (subject or '') + '\n' + latest
    if cls.work_requested:
        # A new inventory article is NOT an inspection/PO/maintenance plan.
        correction_detail = _PLAN_ACTION.search(subject or '') and _PLAN_CHANGE_DETAIL.search(latest)
        if cls.domain != 'PLAN' or not _PLAN_SIGNAL.search(scope) or not (_PLAN_ACTION.search(latest) or correction_detail):
            return replace(cls, review_required=True,
                           reason='REVIEW_REQUIRED: concrete planidentificatie ontbreekt: ' + cls.reason)
    if cls.ei_relevant:
        if cls.domain not in ('EI', 'PLAN') or not _EI_SIGNAL.search(latest):
            return replace(cls, review_required=True,
                           reason='REVIEW_REQUIRED: elektrische/instrumentatiecontext niet bevestigd: ' + cls.reason)
        if (_MECHANICAL_SIGNAL.search(cls.evidence) and not _EI_SIGNAL.search(cls.evidence)) or (
                _MECHANICAL_SIGNAL.search(scope) and not _EI_SIGNAL.search(latest)):
            # Reject mechanically grounded evidence despite E&I words in signature/subject.
            return replace(cls, review_required=True,
                           reason='REVIEW_REQUIRED: overwegend mechanisch / gemengde context: ' + cls.reason)
    return cls


def decide_forward(categories, system_message, cls):
    """Category is a real Outlook property; only supported E&I/plan intents pass."""
    if system_message:
        return 'SUPPRESS_SYSTEM_HAMZA' if has_hamza_category(categories) else 'SUPPRESS_SYSTEM'
    if cls is not None and cls.message_intent in ('COMPLETED', 'STATUS_ONLY') and not cls.review_required:
        return 'SUPPRESS_' + cls.message_intent
    if cls is not None and cls.message_intent == 'UNCLEAR' and cls.intent_evidence and cls.review_required:
        return 'REVIEW_REQUIRED'
    if has_hamza_category(categories):
        return 'SEND_HAMZA'
    if cls is None or cls.review_required:
        return 'REVIEW_REQUIRED'
    if cls.confidence <= MIN_CONFIDENCE_EXCLUSIVE:
        return 'REVIEW_REQUIRED'
    # Plan work is registered independently; it never authorizes forwarding.
    if cls.ei_relevant and cls.domain in ('EI', 'PLAN'):
        return 'SEND_EI'
    return 'SKIP_NOT_RELEVANT'
