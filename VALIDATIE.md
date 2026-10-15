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


1.7.1: de latere gebruikersinstructie maakt afronding/status zonder nieuwe actie
een uitzondering op de oorspronkelijke altijd-Hamza-regel. Nieuwe tests
controleren afgerond roostervloerenwerk met/zonder Hamza, negatie, geciteerde
oude opdracht, gemengd afgerond/nieuw werk, letterlijke modelonderbouwing
en onzekere statusclaims. Het echte roostervloerenbericht is niet aangeleverd;
de exacte oorzaak van de vroegere verzending is dus niet vastgesteld.
59 agenttests en 3 updatertests slagen. De vorige 1.7.0-run is door de
aangeleverde Windows-uitvoer bevestigd als RUNNING met geslaagde scan en
forwarding enabled; nieuwe classificaties en modelkwaliteit moeten nog
op Windows met echte berichten gevalideerd worden.


1.7.2: onderhoudsitem- en intervalcorrecties krijgen expliciete promptinstructies,
herkenning van aan-te-passen-formuleringen en maximaal een tweede semantische
beoordeling bij een negatief antwoord over mogelijk planwerk. Vier nieuwe tests
controleren verkorte intervalcorrectie met letterlijk bewijs, herstel van een
negatieve modelbeoordeling, geen extra call voor afgerond werk en eenmalige
herbeoordeling van bestaande REVIEW_REQUIRED-kandidaten zonder inhaalforwards.
64 agenttests en 3 updatertests slagen. Geen echte mailbox- of modeltest in deze
cloud; de inhoud van de gemiste mail is alleen als auditfragment beschikbaar.
De AI kan ambiguiteit nog steeds naar review verwijzen. De voorbeeld-ID in de
nieuwe regressietest is fictief.

Een extra regressietest controleert dat een al klaargezette Hamza-mail met
uitgestelde AI-beoordeling alsnog uit de verzendqueue verdwijnt als de
nieuwste tekst ondubbelzinnig afgerond werk meldt.
