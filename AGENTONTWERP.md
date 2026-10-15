# Onderzoek en ontwerpbeoordeling — 15 oktober 2026

Doel: een lokale EE-Reliability-agent die semantisch beoordeelt wat nu voor de
gebruiker relevant is, met weinig modelaanroepen, controleerbare acties en
herstelfuncties. De huidige rolkennis is ondersteuning, geen uitputtende
woordenlijst. Er is geen nieuw taalmodel getraind.

## Geraadpleegde primaire bronnen

- [AgentDojo — ETH Zurich / Invariant Labs](https://github.com/ethz-spylab/agentdojo),
  met expliciete [e-mailtaken in de workspace-suite](https://github.com/ethz-spylab/agentdojo/blob/main/src/agentdojo/default_suites/v1/workspace/user_tasks.py).
  De bron richt zich op taken en prompt-injectieaanvallen/-verdedigingen. Onze
  toepassing: e-mailinhoud als onbetrouwbare gegevens behandelen, begrensde
  tools en ontvanger behouden, en misleidende broninstructies in acceptatietests.
- [τ-bench / actuele τ³-repository](https://github.com/sierra-research/tau2-bench),
  in het bijzonder [Task Schema and Evaluation](https://github.com/sierra-research/tau2-bench/blob/main/docs/evaluation.md).
  Deze documentatie onderscheidt een voorbeeldtraject van het vereiste
  eindresultaat. Onze toepassing: naast modelvelden ook de daadwerkelijke
  forwardingbeslissing en het al dan niet actieve werkitem toetsen; veilige
  review is toegestaan wanneer informatie ontbreekt. De oude tau-bench-repo
  waarschuwt dat zijn taken verouderd zijn; daarvoor is de opvolger geraadpleegd.
- [Anthropic Building Effective Agents — officiële referentie-implementaties](https://github.com/anthropics/anthropic-cookbook/tree/main/patterns/agents),
  inclusief [Evaluator-Optimizer](https://github.com/anthropics/anthropic-cookbook/blob/main/patterns/agents/evaluator_optimizer.ipynb).
  De notebook laat een aparte evaluatiestap met feedback zien. Onze toepassing:
  hoogstens één extra herbeoordeling; geen onbeperkte zelfreflectielus en geen
  extra model/server. Het voorbeeld is een patroon, geen bewijs dat dezelfde
  Qwen zijn eigen fouten betrouwbaar ontdekt.

De originele Anthropic-webpagina en arXiv waren vanuit deze omgeving niet
bereikbaar (proxy 403). Bovenstaande officiële GitHub-bronnen en broncode zijn
wel daadwerkelijk opgehaald en gelezen. Er is geen MailBench-paper gelezen
of mailbox-benchmark uitgevoerd. Er zijn geen bedrijfsmails naar deze bronnen
verstuurd. De hier beschreven toepassing is onze ontwerpkeuze, geen claim dat
het pakket deze benchmarks haalt.

## Wat moet deze agent aantoonbaar kunnen?

| Vraag | Implementatie 1.9.0 | Resterende grens |
| --- | --- | --- |
| Begrijpt hij onbekende termen? | Letterlijk bewijs plus twee overeenstemmende semantische beoordelingen kunnen een lexicale afwijzing overrulen. Eigenaar, timing, domein en concrete actie worden gecontroleerd. | Twee antwoorden van hetzelfde model zijn gecorreleerd en kunnen beide fout zijn. |
| Kent hij de rol? | 18 begripsclusters met 152 NL/EN-benamingen en relaties, begrensd tot relevante context. | Startset; lokale SAP-inrichting en onbekende betekenis zijn niet volledig bekend. |
| Begrijpt hij een gesprek? | Nieuwste tekst, geciteerde geschiedenis en maximaal drie eerdere lokale beslisrecords worden onderscheiden. | Lokale records zijn gegenereerde context, geen bewijs van actuele opdracht of zakelijke voltooiing. |
| Kan hij zich corrigeren? | Maximaal twee modelgeneraties per classificatie. Tegenstrijdige positieve acties worden REVIEW_REQUIRED. Oude reviews krijgen eenmaal per beleidsversie een rapport-only herbeoordeling. | Geen onbeperkte autonome hertraining of automatische inhaalverzending. |
| Begrijpt hij timing en verantwoordelijkheid? | ACTION_REQUIRED, COMPLETED, STATUS_ONLY, DEFERRED, OUT_OF_SCOPE, UNCLEAR met eigenaar, timing, actie en bewijs. | Ontbrekende roltoewijzing kan menselijke beoordeling vereisen. |
| Voert hij acties betrouwbaar uit? | Vaste forwardingroute, historische baseline, SQLite-reservering vóór Send, UNKNOWN bij ambiguïteit, geen blinde retry. | Outlook Send betekent submission, niet bewezen ontvangst. EntryID is de bestaande deduplicatiesleutel; verplaatsing/kopie met nieuwe ID kan aanvullende identiteit vergen. |
| Kan hij broninstructies onderscheiden? | Mailvelden als JSON-data; bron mag beleid, ontvangers en tools niet kiezen. Het model kan zijn eigen semantic_verified-vlag niet zetten. | Datagrenzen en tests voorkomen niet alle prompt-injecties. |
| Is ontbrekende informatie zichtbaar? | Review bij te lange actuele tekst of onvoldoende tekst over een bijlage; review_queue.csv met reden en actievelden. | De agent leest de inhoud van bijlagen, screenshots en SAP zelf nog niet. |
| Blijft hij zuinig? | Eén Qwen, standaardbibliotheek/JSON, geen vectorserver, begrensd 8192-tokenvenster, verwerkte mails niet opnieuw classificeren, maximaal twee generaties, model-unload na batch. | Werkelijke RAM/CPU en latentie zijn nog niet in deze cloud gemeten. |
| Is de beoordeling aantoonbaar goed? | 21 inhoudelijke modelcases vóór codewissel; rapport met false/missed forwards en ontbrekende/onverwachte actieve werkitems. | Kleine synthetische set, geen prestatiewaarborg voor de hele echte mailbox. |

## Testen en vrijgave

De 1.9.0-regressies testen ook ongekende E&I-/planformuleringen, model-
onenigheid, bewijs uit oude quotes, ontvanger-/verified-injectie, handtekeningen,
te lange berichten, begrensd gespreksgeheugen en verzending over herstarten.
Deze tests gebruiken gesimuleerde modelantwoorden en tijdelijke databases.

De echte lokale Qwen-test is een afzonderlijke gate in UPDATE.bat, vóór stoppen
of vervangen van de bestaande agent. Die test is hier niet uitgevoerd omdat
de cloud geen Ollama heeft. Hij vergelijkt bedrijfsuitkomsten, niet een exact
voorgeschreven reden of denkproces. Voor evaluatie kunnen dezelfde gevallen
opnieuw worden gedraaid; een cache wordt alleen hergebruikt bij identieke
code, kennis, suite en modeldigest. Dit is geen meting van pass^k of een
statistisch gekalibreerde foutkans.

De volgende inhoudelijke kwaliteitsmeting hoort een geanonimiseerde,
onafhankelijk gelabelde set echte mails te gebruiken, met aparte voorbeelden
voor afstemming en eindtoets. De echte mailboxgeschiedenis is niet openbaar
in de repository opgenomen en wordt niet als zelfgegenereerde waarheid gebruikt.
