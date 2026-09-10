# Kooperativer Scheduler für parallele Events

## Ziel

Der nächste Runtime-Slice führt mehrere parallele Common Events und Map-Events
in einem gemeinsamen, deterministischen Frame-Takt aus. Er baut auf dem
vorhandenen Event-Trace-Interpreter auf, ersetzt ihn aber nicht durch eine
zweite Ausführungslogik. Der bisherige Einzellauf bleibt die bequeme
Diagnoseschnittstelle; intern soll er künftig denselben fortsetzbaren
Interpreterkern wie der Scheduler verwenden.

Der Slice ist noch keine vollständige Spielszenen-Laufzeit. Er soll jedoch die
erste Architektur liefern, in der dauerhaft laufende RPG-Maker-Prozesse ihren
Kontrollfluss über Frames hinweg behalten und gemeinsam Switches, Variablen,
Charakter-Snapshots und Pictures verändern können.

Einzellauf und Scheduler verwenden denselben Befehls- und Kontrollflusskern.
Nur der Scheduler lässt Waits kooperativ stehen; der bestehende Einzellauf
behält seine synchrone Diagnose-Semantik und bleibt damit rückwärtskompatibel.

## Warum ein fortsetzbarer Interpreter nötig ist

`EventTraceRunner.run()` führt derzeit eine Befehlsliste synchron bis zum
Abschluss, einem Wait-Checkpoint oder einem anderen Haltegrund aus. Ein Wait
verschiebt dabei sofort die globale Frame-Zeit. Dieses Modell ist für einzelne
reproduzierbare Vorschauen richtig, kann parallele Prozesse aber nicht fair
ineinander verschachteln.

Ein Scheduler darf einen Eventlauf nach einem Wait auch nicht mit
`start_index` neu aufbauen. Dabei gingen verschachtelte Common-Event-Aufrufe,
Schleifenstände und Sprungpfade verloren. Stattdessen wird der vorhandene
Interpreterzustand in eine fortsetzbare Session überführt:

- ein Stack aus Befehlsframes mit aktuellem Index und Schleifenzählern;
- der Quelltyp samt Common-Event-, Map-Event- und Seiten-ID;
- ein tasklokaler Wait-Zähler und ein expliziter Ausführungsstatus;
- kumulierte Befehls-, Restart- und Fehlerdiagnosen;
- ein Verweis auf genau einen gemeinsam genutzten `TraceContext`.

Die öffentliche `EventTraceRunner.run()`-Schnittstelle bleibt für bestehende
Aufrufer und Resultate kompatibel; der Scheduler ergänzt sie um eine
fortsetzbare Session-API.

## Datengrundlage in Darkest Journey

Die read-only ausgewerteten Originaldaten enthalten zehn Common Events mit
Parallel-Trigger. Acht davon haben eine aktive Switch-Bedingung, Event 1 läuft
ohne Switch-Bedingung und Event 22 besitzt keine Befehle. Unter anderem gehören
dazu:

| Common Event | Name | Aktivierung | Befehle |
|---:|---|---|---:|
| 1 | `Alles aus` | immer | 5 |
| 3 | `Taschenlampe` | Switch 62 | 77 |
| 6 | `Kampfsystem` | Switch 7 | 180 |
| 12 | `Menue_Start()` | Switch 12 | 48 |
| 13 | `Menue_Steuerung()` | Switch 222 | 183 |
| 16 | `Menue_Beenden()` | Switch 227 | 31 |

Über die 84 parsebaren Maps verteilen sich außerdem 154 parallele
Map-Seiten. 107 davon besitzen keine Seitenbedingung; die übrigen verwenden
Switch-, Variablen- oder kombinierte Bedingungen. Der Scheduler ist daher kein
späteres Komfortmerkmal, sondern Voraussetzung dafür, typische Karten korrekt
weiterlaufen zu lassen.

Der erste Originaldaten-Akzeptanzfall ist Map0064. Dort können gleichzeitig
Common Event 1, bei aktivem Switch 62 die Taschenlampe sowie die bedingungslose
erste Seite von Event 17 (`Herz`) laufen. Wird Switch 97 aktiv, muss Event 17
auf seine höhere zweite Seite wechseln, den alten Interpreterzustand
verwerfen und den neuen Seitenlauf erst beim nächsten Event-Update beginnen.

## Scheduler-Modell

### Frame-Reihenfolge

Ein vollständiger Scheduler-Frame erhält eine feste Reihenfolge:

1. fällige Seiten- und Switch-Aktivierungen aus dem gemeinsamen Zustand
   bestimmen;
2. parallele Common Events in aufsteigender Datenbank-ID fortsetzen;
3. parallele Map-Events in aufsteigender Event-ID fortsetzen;
4. laufende globale Picture-Übergänge genau einmal um einen Frame
   fortschreiben;
5. Frame-Zähler und Diagnose-Timeline abschließen.

Diese Reihenfolge folgt der EasyRPG-Map-Laufzeit: Common Events werden vor
Map-Events aktualisiert, beide jeweils in ihrer gespeicherten Reihenfolge;
Pictures werden anschließend global aktualisiert. Die Reihenfolge wird als
beobachtbares Kompatibilitätsverhalten getestet und nicht von Dictionary-
Iteration oder Dateisystemreihenfolge abhängig gemacht.

Ein Event darf innerhalb seines Zeitslots mehrere nicht blockierende Befehle
ausführen. Es gibt den Slot ab, sobald es wartet, externe Unterstützung
benötigt, abgeschlossen ist oder sein Befehlsbudget für den Frame erreicht.
So bleiben typische RPG-Maker-Befehlsfolgen atomar genug, ohne dass ein
endloser Prozess andere Events verdrängt.

### Waits und Picture-Bewegungen

Ein normaler Wait speichert den frühesten Resume-Frame des Tasks. Dauer null
bedeutet genau einen Scheduler-Frame; andere Werte werden weiterhin mit
`duration * fps / 10` umgerechnet. Ein im Frame N ausgeführtes `Wait 0` gibt
also den restlichen Slot ab und darf den nächsten Befehl frühestens in Frame
N + 1 ausführen.

Ein wartender `MovePicture` verwendet dieselbe tasklokale Warteform, während
die eigentliche Interpolation im globalen `PictureState` liegt. Ein nicht
wartender Move gibt den Interpreter sofort frei. Der Scheduler selbst erhöht
die globale Zeit nur einmal pro vollständigem Frame, unabhängig davon, wie
viele Tasks warten.

Damit wird auch die bislang absichtlich vereinfachte Trace-Semantik präziser:
Ein synchroner Einzellauf darf mehrere Scheduler-Frames intern abwickeln,
anstatt die gesamte Wartezeit in einem Sprung auf den Kontext anzurechnen.

### Aktivierung und Neustart

Parallele Common Events erhalten beim Laden einen eigenen Interpreter. Ohne
Switch-Flag sind sie dauerhaft ausführbar; mit Switch-Flag laufen sie nur,
solange der zugehörige Switch aktiv ist. Wird der Switch während eines Waits
ausgeschaltet, bleibt die Session erhalten, wird aber nicht fortgesetzt. Nach
erneuter Aktivierung läuft sie an derselben Stelle weiter.

Erreicht ein aktives paralleles Common Event das Ende seiner Liste, beginnt es
frühestens in seinem nächsten Scheduler-Slot wieder am Anfang. Ein Restart im
selben Slot würde leere oder waitfreie Listen zu einer Endlosschleife machen.

Map-Events verwenden pro Frame die höchste Seite, deren Bedingungen erfüllt
sind. Ändert sich die aktive Seite, wird die bisherige Session verworfen. Für
eine nichtleere parallele neue Seite wird eine frische Session vorbereitet,
aber erst beim nächsten Map-Event-Update gestartet. Gibt es keine gültige
Seite oder ist die neue Seite nicht parallel, existiert kein paralleler Task
für dieses Event.

`EraseEvent` markiert das Map-Event für die aktuelle Karteninstanz als inaktiv
und beendet dessen Session. Ein bloßer Abschluss der Befehlsliste löscht das
Event dagegen nicht; solange dieselbe Parallelseite aktiv bleibt, wird sie im
nächsten Slot neu gestartet.

### Gemeinsamer Zustand und Refresh

Alle Tasks arbeiten auf demselben `TraceContext`. Änderungen an Switches oder
Variablen sind deshalb für später im Frame ausgeführte Tasks sofort sichtbar.
Eine dadurch angeforderte Seitenaktualisierung wird vor dem nächsten
auszuführenden Befehl ausgewertet. Wechselt ein Map-Event dabei seine eigene
Seite, endet sein aktueller Zeitslot sofort; die neue Seite beginnt nicht noch
im selben Update.

Diese Refresh-Regel ist wichtig für Event 17 auf Map0064 und verhindert, dass
Befehle der alten und neuen Seite in einem künstlichen Mischzustand laufen.

### Blockierte und fehlerhafte Tasks

Ein paralleler Task darf einen fehlenden Laufzeitdienst nicht als normalen
Wait behandeln. Nachrichten, Tasteneingaben, Bewegungsrouten und andere noch
nicht implementierte Dienste setzen ihn auf einen sichtbaren Status wie
`awaiting_input` oder `unsupported`. Andere unabhängige Tasks dürfen im
Diagnosemodus weiterlaufen.

Das Scheduler-Ergebnis enthält mindestens:

- Gesamtstatus, Framezahl und ausgeführte Befehle;
- stabile Task-ID, Quelle, aktive Seite, Status und Wait-Zähler je Task;
- Start-, Pause-, Resume-, Restart-, Seitenwechsel- und Blockadeereignisse;
- den vorhandenen Befehls-Pfad samt globalem Frame;
- finalen gemeinsamen Zustand einschließlich Pictures und Aktionen.

Ein strikter Modus darf den gesamten Lauf beim ersten blockierten Task
anhalten. Standard für Analyse und Vorschau bleibt ein Diagnosemodus, der den
Task isoliert und den restlichen Scheduler bis zum Gesamtbudget fortsetzt.

## Budgets

Der Scheduler ergänzt die vorhandenen Trace-Grenzen um:

- maximale Scheduler-Frames;
- maximale Befehle pro Task und Frame;
- maximale Gesamtbefehle;
- maximale Restarts pro Task;
- weiterhin maximale Schleifendurchläufe und Call-Tiefe pro Session.

Ein ausgeschöpftes lokales Budget lässt den Task bis zum nächsten Frame
yielden. Ein ausgeschöpftes Gesamt-, Frame- oder Restart-Budget beendet den
Lauf mit `budget_exhausted`. Dadurch sind sowohl waitfreie Parallelprozesse als
auch unbeabsichtigte Neustartschleifen reproduzierbar begrenzt.

## Umgesetzter erster Implementierungsslice

Der erste Code-Slice ist bewusst klein, aber architektonisch vollständig:

1. `EventTraceRunner` besitzt mit `TraceSession` einen fortsetzbaren
   Interpreterzustand; die öffentliche `run()`-Schnittstelle und die
   bestehenden Regressionstests bleiben kompatibel.
2. `ParallelScheduler` führt explizit geladene parallele Common Events und die
   aktive Map in stabiler Reihenfolge aus.
3. Common-Event-Switches sowie Map-Seiten ohne Bedingung und mit Switch- oder
   Variablenbedingung werden unterstützt; Item-, Actor- und Timerbedingungen
   bleiben sichtbare Grenzen.
4. Wait, wartender `MovePicture`, Abschluss, Restart, Seitenwechsel und
   `EraseEvent` sind echte Yield- beziehungsweise Lebenszyklusereignisse.
5. `run_scheduler.py` stellt JSON-Diagnose für einen begrenzten Frame-Ausschnitt
   bereit; eine Live-Eingabe- oder Fensterschleife bleibt vertagt.

## Abnahmetests

Synthetische Tests sichern zunächst die Mechanik:

- zwei Tasks ändern im selben Frame denselben Switch oder dieselbe Variable in
  dokumentierter Reihenfolge;
- `Wait 0` blockiert nur seinen Task und die globale Zeit steigt genau einmal;
- ein verschachtelter Common-Event-Aufruf wird nach einem Wait mit erhaltenem
  Call-Stack fortgesetzt;
- ein abgeschlossener Parallelprozess startet erst im nächsten Slot neu;
- Ausschalten und erneutes Einschalten eines Common-Event-Switches pausiert und
  reaktiviert dieselbe Session;
- ein Map-Seitenwechsel verwirft die alte Session und startet die neue Seite
  um ein Update verzögert;
- ein blockierter Task stoppt andere Tasks im Diagnosemodus nicht;
- lokale und globale Budgets melden unterscheidbare Haltegründe.

Danach folgen read-only Prüfungen mit den Originaldaten:

- Common Event 3 hält den Taschenlampen-Slot über mehrere `Wait 0`-Frames an
  der Spielerposition und reagiert auf einen Richtungswechsel;
- Map0064/Event 17 durchläuft die 90-Frame-Herzanimation und startet sie
  erneut, ohne zusätzliche Picture-Slots anzulegen;
- Switch 97 wechselt Event 17 sauber auf Seite 1, löscht Slot 20 und erzeugt
  Slot 19;
- mehrere auf Map0064 gleichzeitig aktivierte Prozesse ergeben bei gleichem
  Startzustand bytegleiches JSON.

## Bewusst vertagt

- Vordergrund-, Autorun-, Berührungs- und Action-Key-Planung
- echte Tastatur-, Nachrichten- und Choice-Anbieter
- vollständige Bewegungsrouten und Kollisionsupdates
- Item-, Actor-, Timer- und Timer-2-Seitenbedingungen
- Kartenwechsel und persistente Map-Instanzen
- LSD-Speicherung laufender Scheduler- und Interpreterzustände
- genaue Nachbildung mehrfacher Map-Event-Updates durch Kollisionen
- Audioausgabe, Fensterschleife und interaktive Darstellung

## Referenzsemantik

Die Reihenfolge und Lebenszyklen wurden gegen die Primärimplementierung von
EasyRPG abgeglichen:

- [Map-Update und Reihenfolge paralleler Events](https://raw.githubusercontent.com/EasyRPG/Player/master/src/game_map.cpp)
- [Aktivierung paralleler Common Events](https://raw.githubusercontent.com/EasyRPG/Player/master/src/game_commonevent.cpp)
- [Map-Seitenwechsel und parallele Map-Events](https://raw.githubusercontent.com/EasyRPG/Player/master/src/game_event.cpp)
- [Fortsetzbarer Interpreter und Wait-Zähler](https://raw.githubusercontent.com/EasyRPG/Player/master/src/game_interpreter.cpp)
