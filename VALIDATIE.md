# Beoordeling en validatie

Bronnen: volledige app.zip plus de drie auditmodules, helper en bijgewerkte
regressietests uit het aangeleverde 1.6.1-updatepakket. Bijlagen zijn als
bronmateriaal beoordeeld; er zijn geen oorspronkelijke BAT/PS1 scripts uitgevoerd.
De oorspronkelijke uploads en lege repository-README zijn behouden.

De originele app-suite had zes falende assertions in 21 tests. Die tests
verwachtten oudere beslisstructuren zonder domein/bewijsvelden. Het meegeleverde
1.6.1-pakket bevat daarvoor actuele fixtures. Deze zijn overgenomen en de
planverwachtingen expliciet aangepast aan het gewenste aparte werkitemsbeleid;
assertions zijn niet uitgezet. De 78 mails in audittests zijn fictieve fixtures.

Bevestigde codeproblemen en correcties:

- Plan-only classificatie gaf SEND_PLAN. Dit geeft nu SKIP_NOT_RELEVANT voor
  forwarding, met behoud van het afzonderlijke werkitem. E&I plus plan mag
  SEND_EI geven wanneer er ook E&I-bewijs in de nieuwste boodschap staat.
- Een niet-Hamza AI-fout brak de scan af. De scan verwerkt nu de overige
  metadata en Hamza-regels, bewaart fouten en rapporteert geen scansucces.
- Een Hamza-categorie die na REVIEW_REQUIRED verscheen werd genegeerd.
  Ze krijgt nu dezelfde herbeoordeling als een later gecategoriseerde SKIPPED mail.
- Heartbeat op dezelfde thread als generatie kon onterecht stale worden.
  De aparte thread heeft een eigen SQLite-verbinding en stopt gecontroleerd.
- Windows-handle-sluiting had geen pointertype. CloseHandle heeft nu een
  expliciete 64-bit-veilige signatuur.
- Modelresidency was niet expliciet begrensd. Generatie krijgt 30 seconden,
  batch-einde vraagt unload; werking op echte Ollama is nog niet gemeten.
- Main daemon bleef Outlook COM-initialisaties opbouwen. De gekoppelde gateway
  krijgt gecontroleerde cleanup bij constructiefouten, snapshotretry en scan-einde.
- Onzekere werkitems konden bij update OPEN blijven. Nieuwe onzekere aanwijzingen
  escaleren de bestaande reviewstatus naar REVIEW_REQUIRED.

Nieuwe tests onderzoeken onder andere outage vóór latere Hamza-mail, maximaal
één AI-poging tijdens dezelfde outage, herstel zonder duplicaat, oude plan-queue
zonder aantasting van SENT/UNKNOWN, E&I-bewijs bij gecombineerde planverzoeken,
heartbeat tijdens stilstaande main thread, modelresidency in requests, een
onzekere forward na mogelijke submission, late Hamza op REVIEW_REQUIRED en
beperkte retry van daadwerkelijk geweigerde verbindingen.

Niet live bevestigd: Windows-COM, PowerShell-updater/rollback, de Windows-
mutexen, Ollama-start als subprocess, modelkwaliteit, werkelijke RAM/CPU,
login-start en echte forward/delivery. Er is hier niets naar e-mailontvangers
verzonden en geen wijziging op de Windows-pc uitgevoerd.


Updater-correctie 13 oktober 2026: wachten op een eerste scan geeft nu exit 2
zonder traceback op stderr. PowerShell behandelt dat als wachten, niet als
installatiefout. Drie nieuwe subprocess-tests controleren ontbrekende status,
onvoltooide/eerste geslaagde scan, echte scanfout en beschadigde status.
54 agenttests en 3 updatertests slagen. PowerShell zelf is hier niet uitgevoerd.
