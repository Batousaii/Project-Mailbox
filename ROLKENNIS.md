# Rolkennis 2.0.0

EE-Reliability: E&I-werk en SAP PM-onderhoudsplanning

Deze kennis vormt een beheerde, uitbreidbare basis. Qwen leest relevante begrippen en hun relaties per bericht. Termherkenning alleen autoriseert geen forward of SAP-handeling.

| Begrip | NL/EN-benamingen | Relaties |
| --- | --- | --- |
| Onderhoudsplan / maintenance plan | onderhoudsplan, onderhoudsplannen, maintenance plan, maintenance plans, PO-plan, PO plan, PM-plan, PM plan, inspectieplan, inspectieplannen, inspection plan | MAINTENANCE_ITEM, STRATEGY, CYCLE, SCHEDULING |
| Onderhoudsitem / maintenance item | maintenance item, maintenance items, onderhoudsitem, onderhoudsitems, planitem, plan item | MAINTENANCE_PLAN, TASK_LIST, TECH_OBJECT |
| Onderhoudstaaklijst | onderhoudstaaklijst, maintenance task list, task list, taaklijst, taaklijsten, werklijst onderhoud | OPERATION, MAINTENANCE_ITEM, STRATEGY |
| Onderhoudsstrategie | onderhoudsstrategie, maintenance strategy, strategy plan, strategieplan, strategie plan | PACKAGE, CYCLE, MAINTENANCE_PLAN |
| Onderhoudspakket | onderhoudspakket, maintenance package, maintenance packages, cycluspakket, pakketindeling | STRATEGY, OPERATION, CYCLE |
| Cyclus en periodiciteit | periodiciteit, periodicity, onderhoudsinterval, maintenance interval, onderhoudscyclus, maintenance cycle, frequentie, frequency, 6M, 12M, 3M, 5J, 5Y | MAINTENANCE_ITEM, PACKAGE, SCHEDULING |
| Afroep en planningsparameters | scheduling parameters, planningsparameters, call horizon, afroephorizon, shift factor, verschuivingsfactor, scheduling indicator, startdatum, cycle start, afroep, afroepen | MAINTENANCE_PLAN, WORK_ORDER, CYCLE |
| Onderhoudsbewerking | onderhoudsbewerking, onderhoudsbewerkingen, maintenance operation, maintenance operations, planregel, planregel verwijderen, regel verwijderen | TASK_LIST, PACKAGE |
| Technisch object | equipment, equipmentnummer, functional location, functieplaats, technische plaats, technisch object, tagnummer, tag number, asset | MAINTENANCE_ITEM, WORK_ORDER |
| Werkorder | werkorder, work order, maintenance order, onderhoudsorder, PM-order, PM order, werkbon | NOTIFICATION, TECH_OBJECT, MAINTENANCE_PLAN |
| Onderhoudsmelding | onderhoudsmelding, maintenance notification, storingsmelding, malfunction report, defectmelding | WORK_ORDER, TECH_OBJECT |
| Technische stuklijst | stuklijst, stuklijsten, bill of materials, BOM, equipment BOM, spare parts list | SPARES, TECH_OBJECT |
| Reserveonderdelen en magazijn | spare part, spare parts, reserveonderdelen, wisselstukken, magazijnartikel, voorraad, stock, materiaalstam, material master | BOM, ELECTRICAL, INSTRUMENTATION, MECHANICAL |
| Elektriciteit en automatisering | E&I, elektrisch, elektrische, electrical, PLC, DCS, SCADA, VFD, frequentieomvormer, schakelkast, bekabeling, elektromotor, isolatiemeting, aardingsmeting | INSTRUMENTATION, SPARES |
| Instrumentatie en kalibratie | instrumentatie, instrumentation, kalibratie, calibration, kalibreren, sensor, transmitter, druktransmitter, flowmeter, debietmeter, thermokoppel, meetlus, regelklep, control valve | ELECTRICAL, SPARES |
| Mechanisch onderhoud | mechanisch, mechanical, lager, bearing, gearbox, tandwielkast, pakking, dichting, check valve, filter, leiding, piping | MAINTENANCE_PLAN, SPARES |
| Inkoop en purchase orders | purchase order, purchase requisition, inkooporder, bestelbon, inkoopaanvraag | SPARES |
| Uitvoering en afronding | uitgevoerd, afgerond, voltooid, completed, performed, klaar, aangepast | WORK_ORDER, MAINTENANCE_PLAN |

De begripsdefinities en uitzonderingen staan in `app/agent/role_knowledge.json`. Lokale SAP-inrichting en onbekende afkortingen kunnen aanvullende, gecontroleerde kennis vereisen. Een nieuwe kennisversie moet opnieuw de inhoudelijke modeltest doorstaan. Dit is geen zelftraining op e-mailinhoud.

Timing en eigenaarschap: een toekomstige mogelijkheid na een externe
mijlpaal en zonder taak voor jouw rol is DEFERRED/OUT_OF_SCOPE, geen huidige
forward of actief werkitem. Een concrete voorbereidingsopdracht aan jou is
wel actie, ook bij latere uitvoering. Onduidelijkheid wordt niet ingevuld.

De voorbeelden zijn geen gesloten whitelist. Semantisch onderbouwde herkenning
van nieuwe termen kan de lexicale controle overrulen na twee overeenstemmende
beoordelingen met bewijs, eigenaar en timing. Beide beoordelingen gebruiken
hetzelfde model, dus kunnen dezelfde fout maken.

