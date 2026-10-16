# Validatie en acceptatie 2.0.0

Gebouwd op 16 oktober 2026. Basis: 1.9.0, commit 7eee68f op de eerdere ontwikkelbranch.
De doelen uit AGENTONTWERP.md en LEESMIJ.txt zijn meegenomen. Het volledige eerdere chatgesprek
is niet via een chatgeschiedenistool beschikbaar; de bewaarde projectnotities zijn de bron.

In deze Linux-cloud uitgevoerd:

- 95 agenttests: 86 bestaande plus 9 nieuwe regressies, allemaal geslaagd.
- 3 bestaande updatertests: geslaagd.
- Python-compilecontrole: geslaagd.
- Nieuwe regressies: SUBMITTED versus SENT, geen retry na restart, ambiguïteit bij COM,
  activatie hervatten zonder tweede test-send, ontvangstbevestiging, CSV-escaping,
  maandrapport voor onbevestigde sends, SQLite-duurzaamheid, rustige stop en lokale proxy-instelling.

Geen echte e-mails verstuurd. De tests gebruiken tijdelijke SQLite-databases, gesimuleerde
Outlook-objecten en gesimuleerde modelantwoorden. Ze bewijzen geen modelkwaliteit.
De 21 echte Qwen-cases zijn hier niet uitgevoerd; UPDATE/INSTALL voert ze op de doel-pc uit.

## Nog verplicht op Windows

1. Preflight op echte Python/venv/pip/pywin32, Ollama-server/model/generatie, klassieke Outlook en juiste bestaande Inbox.
2. Gatefouten met ontbrekende Python of gestopte/onbereikbare Ollama: geen baseline/startup bij falen; recovery aantonen.
3. Historische metadata-baseline met nul automatische forwards; oude data/audits behouden bij update.
4. Gecontroleerde test-forward met expliciete goedkeuring, Sent Items en ontvangstbevestiging.
5. Nieuwe Hamza-mail en E&I-spareparts: elk eenmaal; mechanisch/status/automatisch: geen ongewenste forward.
6. Nieuwe/gewijzigde inspectie- én PO-plannen: juiste aparte werkitems met gelijke prioriteit; geen impliciete E&I-forward.
7. RE met nieuw verzoek, oude quotes, SAP PM-periodiciteit, rol/eigenaar en timing: representatieve NL/EN-mailset.
8. Crash rond Send: UNKNOWN/SUBMITTED zichtbaar, geen dubbele mail na restart; reconciliatie naar SENT testen.
9. UPDATE: goedkeuring en EntryIDs behouden; precies één worker en nieuwe succesvolle scan; code-rollback zonder DB-rollback.
10. Loginstart en volgende 12-uurscyclus zonder handwerk; Ollama-/Outlook-herstel, logboek en maandcontrole.
11. Schone INSTALL, START/STOP/UNINSTALL en PowerShell-organisatiebeleid. Die scripts zijn hier niet op Windows uitgevoerd.

Verdere grenzen: bijlagen/SAP worden niet gelezen; zelfgerapporteerde confidence is niet gekalibreerd;
hetzelfde model tweemaal raadplegen is geen onafhankelijke waarheid; Sent Items is geen aflevergarantie.
Geërfde 1.x-SENT-statussen behouden hun eerdere betekenis. Het apparaat moet aan en aangemeld zijn.
De maandcontrole toetst bekende onopgeloste berichten, niet alle mogelijke AI-foutnegatieven.
Zonder lokale resultaten en actieve scheduler/forwarding is de oorspronkelijke harde oplevereis nog open.
