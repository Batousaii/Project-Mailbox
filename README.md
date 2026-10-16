# EE-Reliability 2.0.0

Windows-agent voor klassieke Outlook, gedeelde Inbox EE-Reliability en lokale Ollama qwen3:4b.
Gebaseerd op de bestaande 1.9.0-code en de ontwerpnotities van 15 oktober 2026 op
`codex/ee-reliability-1.7-download` (commit `7eee68f`).

## Gebruiken

Pak **EE-Reliability-2.0.0.zip** helemaal uit op de Windows-pc.

- **Bestaande EE-ReliabilityAgent-installatie:** open klassieke Outlook met de al gekoppelde Inbox en dubbelklik **UPDATE.bat**.
- **Nieuwe installatie:** installeer zo nodig 64-bit Python >=3.10 en Ollama voor de huidige gebruiker; open klassieke Outlook en dubbelklik **INSTALL.bat**.
- **STATUS.bat** toont de werking, forwardingstatus, fouten, modeltest en laatste succesvolle scan.
- **ACTIVATE.bat** is voor eerste activering: nieuwe mail met onderwerp EE-AGENT-TEST en categorie Hamza,
  expliciete goedkeuring voor één forward, controle van Sent Items en bevestiging van werkelijke ontvangst.
  Bestaande activeringsgoedkeuring blijft tijdens UPDATE behouden.

De updater voert vóór codewissel 95 agenttests, 3 updatertests, echte preflight en 21 synthetische
mailcases door het echte lokale model uit. Mislukken die, dan wordt de draaiende agent niet vervangen.
Na codewissel controleert hij precies één proces, heartbeat en een nieuwe succesvolle scan.
Exitcode 2 betekent dat de eerste scan nog niet is bevestigd; zie STATUS.bat.
Een bestaand 1.x-pakket kan tijdens cutover nog gericht beëindigd moeten worden; onzekere
verzendingen blijven dan UNKNOWN, zonder automatische retry. 2.0 ondersteunt een rustig stopverzoek.

Voor nieuwe installatie maakt de installer een eigen venv, start een bestaande Ollama-server indien nodig,
downloadt het ontbrekende model en test echte generatie/COM/mailbox/modeluitkomsten vóór baseline/startup.
Ontbrekende Python/Ollama-installaties worden niet blind vervangen: er volgt een herstelmelding.
Geen adminrechten, nieuwe Exchange-aanmelding of wijzigingen aan originele mailboxitems.
De PC moet aan en de gebruiker aangemeld blijven voor de 12-uurscyclus.

## Wat 2.0 behoudt en verbetert

Behoudt rolkennis (18 begripsclusters), semantische beoordeling met maximaal twee generaties,
letterlijk bewijs, eigenaar/timing, begrensde gesprekscontext, aparte CREATE_PLAN/MODIFY_PLAN-werkstroom,
rapport-only herbeoordeling en historische verzendbeveiliging uit 1.9.
Afgerond werk/status/voorwaardelijk werk voor anderen wordt volgens de bestaande policy onderdrukt,
ook bij Hamza; systeemmails eveneens. Bij AI-storing blijft de Hamza-route mogelijk met uitgestelde plananalyse.
Zie LEESMIJ.txt, ROLKENNIS.md en AGENTONTWERP.md voor de inhoudelijke regels.

Nieuw in 2.0:

- **SUBMITTED** betekent dat Outlook Send accepteerde; pas een aangetroffen kopie in Sent Items geeft **SENT**.
  UNKNOWN en SUBMITTED worden gereconcilieerd, nooit blind opnieuw verzonden. SENT is geen bewijs van aflevering.
  Bestaande 1.x-SENT-records blijven behouden met hun vroegere betekenis en worden nooit opnieuw verstuurd.
- Test-forward vereist ook expliciete ontvangstbevestiging; afgebroken activatie kan met dezelfde test verder zonder tweede forward.
- SQLite gebruikt expliciet volledige transactieduurzaamheid (`synchronous=FULL`).
- STOP.bat en update ondersteunen een coöperatief stopverzoek; START.bat start weer stil.
- Mailtekst kan via CSV-export geen spreadsheetformule starten. Lokale AI-aanroepen gebruiken expliciet geen externe HTTP-proxy.
- INSTALL.bat, ACTIVATE.bat, BACKUP.bat, PAUSE_FORWARDING.bat, SCAN_NOW.bat en UNINSTALL.bat meegeleverd.

## Data en grenzen

Data blijft in `%LOCALAPPDATA%\EE-ReliabilityAgent\data`, inclusief agent.db, logboek en CSV-rapporten.
UPDATE maakt een gecontroleerde databasebackup en bewaart de oude app. Bij codewisselfout wordt code
teruggezet, nooit de database: recente verzenduitkomsten mogen niet verloren gaan. Er is geen automatische
restore van een oude database; die kan latere sends missen en dubbele verzendingen veroorzaken.
Legacy ReliabilityAgentClean wordt geïnventariseerd en volledig geback-upt, niet blind gemigreerd/verwijderd.
Stop de oude agent en zijn startup vóór activatie van een nieuwe installatie.

UNINSTALL.bat stopt v2, verwijdert de door INSTALL aangemaakte v2-Startup-snelkoppeling en maakt een backup.
Data, app/venv, Python, Outlook en Ollama blijven beschikbaar. Historisch geërfde geplande taken worden niet
blind verwijderd; bij een upgrade moeten die apart gecontroleerd worden.

**Validatie hier:** 95 agenttests en 3 updatertests slagen op Linux. Tests gebruiken gesimuleerde AI/Outlook.
Windows PowerShell, echte modelkwaliteit, Outlook-forwarding en een 12-uurs-/loginproef zijn hier niet uitgevoerd.
Dit is een gebouwde 2.0-kandidaat, nog geen bewezen operationele oplevering op de doel-pc.
Zie ACCEPTATIE-2.0.md en TESTRESULTATEN-2.0.txt.
