# Event-Trace-Laufzeit für Pictures

## Entscheidung

Der nächste Portierungsschritt wird ein kleiner, deterministischer
Event-Trace-Interpreter in `05_runtime/`. Er ist weder ein zweiter Renderer
noch bereits eine vollständige RPG-Maker-Laufzeit. Seine Aufgabe ist, eine
konkret ausgewählte Befehlsliste mit ausdrücklich vorgegebenem Spielzustand
bis zu einem nachvollziehbaren Haltepunkt auszuführen.

Der Renderer bleibt ein Verbraucher des Ergebnisses. Dadurch können dieselben
Switch-, Variablen-, Kontrollfluss- und Picture-Regeln später auch von einer
interaktiven macOS-Laufzeit verwendet werden.

## Datengrundlage und notwendige Reichweite

Die Auswertung umfasst alle 84 parsebaren Maps und alle Common Events. In 137
Befehlslisten kommen Picture-Befehle vor: 131 Map-Seiten und 6 Common Events.

| Merkmal | Picture-haltige Befehlslisten |
|---|---:|
| Verzweigungen | 36 |
| Wait-Befehle | 60 |
| Common-/Map-Event-Aufrufe | 17 |
| Labels oder Sprünge | 2 |
| Schleifen | 1 |
| Tasteneingabe | 1 |

Die 115 Bedingungen in diesen Listen verteilen sich auf Switches (43),
Variablen (48), Gegenstände (12) und Charakterrichtung (12). Von 159
`ControlVariables`-Befehlen verwenden 108 Konstanten, 3 direkte Variablen, 4
indirekte Variablen und 44 Charakterwerte. Es kommen dort nur Setzen,
Addieren und Subtrahieren vor.

Damit deckt ein erster Interpreter-Slice mit Switch-, Variablen- und
Richtungsbedingungen bereits die Taschenlampe, den Menü-Pointer und die
einfache Herzanimation ab. Gegenstandsbedingungen, Eingabe und
Bewegungsrouten bleiben sichtbare Grenzen und dürfen nicht stillschweigend
übersprungen werden.

## Rekonstruierte Zielabläufe

### Common Event 3: `Taschenlampe`

Das parallele Common Event wird durch Switch 62 aktiviert und besitzt 77
Befehle. Es zeigt zunächst einen oberen Sichtkegel auf Picture-ID 20, liest
danach Bildschirm-X und -Y des Spielers in die Variablen 41/42 und wählt über
die Blickrichtung einen der vier Kegel:

| Richtung | Wert | Picture |
|---|---:|---|
| oben | 0 | `Sichtkegel_Hoch2` |
| rechts | 1 | `Sichtkegel_Rechts2` |
| unten | 2 | `Sichtkegel_Runter2` |
| links | 3 | `Sichtkegel_Links2` |

Der gewählte Zweig bleibt in einer Schleife, aktualisiert die Variablen 41/42,
bewegt ID 20 ohne Dauer an die neue Spielerposition und führt `Wait 0` aus.
`Wait 0` bedeutet einen Frame. Ändert sich die Richtung, verlässt der Zweig
seine Schleife; der umgebende Parallelprozess wird anschließend neu
gestartet.

Der reproduzierbare Vorschau-Haltepunkt liegt nach dem ersten `Wait 0`. Zu
diesem Zeitpunkt existiert genau ein Slot 20 mit richtiger Grafik und
Spielerposition. Der anfängliche obere Kegel ist im selben Aktivierungslauf
bereits durch den richtungsspezifischen Show-Befehl ersetzt worden.

### Common Events 13/14: Menü-Pointer

Common Event 13 (`Menue_Steuerung()`) ist der 183 Befehle lange,
tastengesteuerte Menüprozess. Er ruft Common Event 14
(`Menue_initAuswahl(1)`) auf. Der erste Slice führt Event 14 direkt mit einem
expliziten Zustand aus; Event 13 benötigt später einen Eingabeanbieter.

Event 14 setzt den Suchbereich auf die Variablen 122 bis 140 für Items oder
142 bis 160 für Notizen. `V114 = V[V112]` liest einen Eintrag indirekt. Ist er
null, springt der Ablauf über Label 1 zum nächsten Eintrag. Der erste Treffer
wird mit der Roh-ID 50113 angezeigt:

- Variable 113 bestimmt die tatsächliche Picture-ID. `FirstStart()` setzt sie
  im Spiel auf 1.
- Variable 114 ersetzt die vier `X` in `Item_XXXX` oder `Notiz_XXXX`.
- Switch 225 wählt Notizen statt Items und wird am Ende wieder ausgeschaltet.

Ein Beispielzustand mit `V113 = 1`, `V122 = 19` erzeugt daher
`Item_0019` auf Slot 1. Mit Switch 225 und `V142 = 5` entsteht entsprechend
`Notiz_0005`.

### Map0002: Zugsequenz

Das Autorun-Event 15 enthält eine komplette Zwischensequenz mit Nachrichten,
Bewegungsrouten, Audio und Teleport. Der erste Zug beginnt bei Befehl 3 als
`train` auf ID 1 bei X = -150 und bewegt sich mit Dauer 70 und aktivem
Wait-Flag bis X = 160. Bei 60 Simulationsframes pro Sekunde sind das 420
Frames beziehungsweise 7 Sekunden.

Später bewegt Befehl 21 denselben Slot bis X = 600 und Befehl 22 löscht ihn.
Für den ersten Slice werden diese Picture-Abschnitte als ausdrücklich
deklarierte, zustandserhaltende Segmente ausgeführt. Das testet Show, wartenden
Move und Erase korrekt, behauptet aber noch nicht, Nachrichten und
Bewegungsrouten der gesamten Zwischensequenz abzuspielen.

### Map0064: Herz

Event 17, Seite 0, ist ein 28 Befehle langer paralleler Aktivierungslauf. Sechs
`ShowPicture`-Befehle ersetzen nacheinander denselben Slot 20 mit `herz2`.
Zwischen den Shows werden die Koordinaten 48/49 aus Event 17 neu gelesen oder
um je einen Pixel verschoben. Die fünf `Wait 2` und das abschließende `Wait 5`
ergeben zusammen 90 Frames.

Nach einem Lauf bleibt deshalb genau ein Slot 20 übrig, nicht sechs Bilder.
Wenn Switch 97 aktiv wird, wählt die Map die höhere Seite: Sie löscht ID 20,
zeigt `herz` auf ID 19 und beendet das Map-Event mit `EraseEvent`.

## Ausführungsmodell

### Zustand

Ein `TraceContext` hält ausschließlich expliziten, serialisierbaren Zustand:

- Switches; nicht gesetzte Switches sind `false`.
- Variablen; nicht gesetzte Variablen sind `0`.
- Charakter-Snapshots mit Map-Koordinaten, Bildschirmkoordinaten und
  Blickrichtung; ID 10001 bezeichnet den Spieler.
- den globalen `PictureState` einschließlich laufender Übergänge.
- aktuelle Simulationszeit in Frames und protokollierte externe Aktionen.

Charakterwerte werden nicht aus einer geratenen Kameraposition abgeleitet,
wenn ein Profil sie nicht eindeutig bereitstellt. In diesem Fall hält der
Trace mit einer erklärbaren Zustandsanforderung an.

### Kontrollfluss

Vor der Ausführung wird jede Befehlsliste validiert und indiziert:

- `ConditionalBranch`, `ElseBranch` und `EndBranch` werden anhand von Ebene
  und Reihenfolge verbunden.
- `Loop`, `BreakLoop` und `EndLoop` erhalten passende Sprungziele.
- Labels werden pro Befehlsliste eindeutig aufgelöst.
- Ein Common-Event-Aufruf legt einen neuen Frame auf einen Call-Stack. Nach
  dessen Ende läuft der aufrufende Frame beim folgenden Befehl weiter.

Malformed oder mehrdeutiger Kontrollfluss wird vor der Ausführung abgelehnt.
Die `END`-Marker mit Code 10 sind Strukturmarker und keine Abbruchbefehle.

### Zeit und Picture-Übergänge

Show wirkt sofort. Move speichert getrennt Start-, aktuelle und Zielwerte
sowie verbleibende Frames. Die Dauer wird wie bei RPG Maker als Zehntelsekunde
interpretiert und mit `duration * fps / 10` in Frames umgerechnet. Der erste
Slice verwendet 60 FPS, hält den Wert aber im Kontext sichtbar.

Ein wartender Move lässt den Interpreter erst nach seiner Dauer weiterlaufen.
Ein nicht wartender Move lässt den Picture-Übergang aktiv, während folgende
Befehle ausgeführt werden. Ein normaler Wait verwendet dieselbe Umrechnung;
Dauer null wartet genau einen Frame. Position, Zoom, Farbton und Transparenz
werden pro Frame linear zum Ziel fortgeschrieben.

### Externe Befehle

Jeder Befehl gehört zu einer von drei Klassen:

1. Zustandsbefehle werden direkt ausgeführt.
2. Nicht blockierende Ausgaben wie `PlaySound` können in einem
   Diagnoseprofil als protokollierte Aktion weiterlaufen.
3. Nachrichten, Tasteneingabe und Bewegungsbefehle besitzen in
   `runtime_providers.py` explizite Anbieter-Verträge. Ein Anbieter liefert
   eine `ProviderDecision`, die einen erfolgreichen Abschluss, einen
   tasklokalen Wait oder einen sichtbaren Haltegrund beschreibt. Ohne den
   passenden Anbieter hält der Trace mit `awaiting_input` an; Choices bleiben
   bis zu einem eigenen Choice-Anbieter bewusst blockiert.

Provider-Ergebnisse dürfen nur ausdrücklich gelieferte Änderungen anwenden:
`KeyInputProc` schreibt den gelieferten Rohwert in seine Zielvariable,
Bewegungsanbieter können konkrete Charakterfelder aktualisieren, und
Nachrichten werden als Aktion mit Originaltext protokolliert. Der
`ScriptedRuntimeProviders`-Adapter stellt dafür eine deterministische
Replay-/Testquelle bereit, ersetzt aber keine macOS-Eingabe- oder
Fensterumgebung.

Damit kann kein unbekannter Befehl unbemerkt den rekonstruierten Zustand
verfälschen.

### Haltegründe und Budgets

Jeder Lauf endet mit einem maschinenlesbaren Grund:

- `completed`
- `checkpoint`
- `awaiting_input`
- `unsupported`
- `budget_exhausted`
- `invalid_data`

Profile müssen Obergrenzen für Befehle, Frames, Schleifendurchläufe und
Call-Tiefe besitzen. Das macht endlose Parallelprozesse reproduzierbar und
Fehler unterscheidbar von beabsichtigten Haltepunkten.

## Implementierter erster Slice

Der implementierte Slice umfasst:

- Map-Seiten und Common Events als explizite Einstiegspunkte oder Segmente;
- Switches mit AN, AUS und Umschalten;
- direkte Variablenziele mit Setzen, Addieren und Subtrahieren;
- konstante, direkte, indirekte und Charakter-Operanden;
- Switch-, Variablen- und Richtungsbedingungen;
- Branches, Labels, Sprünge, Schleifen und Break;
- direkte Common-Event-Aufrufe;
- klassische Show-, Move- und Erase-Picture-Befehle;
- Waits, Framefortschritt und lineare Picture-Übergänge;
- protokollierte Sounds sowie explizite Checkpoints und Budgets;
- explizite Provider-Verträge für Nachrichten, Tasteneingabe und Bewegung;
- kooperative Provider-Waits im Parallel-Scheduler ohne globale Zeitduplikation;
- ein JSON-Ergebnis mit Zustand, Timeline, ausgeführtem Pfad und Haltegrund.

Die vier oben beschriebenen Abläufe wurden mit den Originaldaten read-only
ausgeführt: alle vier Taschenlampenrichtungen, `Item_0019`, der Zugabschnitt
mit 420 Frames, der anschließende Erase-Abschnitt und die 90-Frame-
Herzanimation. Der Trace-Interpreter ist damit als eigenständige Bibliothek
und über `05_runtime/run_trace.py` als Diagnosewerkzeug verfügbar. Die
Anbindung an Renderer-Profile ist über `03_rendering/runtime_preview.py` und
die reproduzierbaren Szenario-Profile abgeschlossen. Der [kooperative
Scheduler](parallel-scheduler-design.md) ist als
`05_runtime/event_scheduler.py` implementiert; Provider werden über dieselbe
Session-API in Common Events und Map-Events geteilt.

## Bewusst vertagt

- interaktive Anbindung von Common Event 13 samt echter Tastatur- und
  Nachrichtenoberfläche
- Gegenstands-, Actor- und weitere Bedingungsarten
- Choice-Anbieter, vollständige Bewegungsrouten und Kollisionen
- Kartenwechsel, Audioausgabe und interaktive Darstellung
- Laden und Fortsetzen eines laufenden LSD-Interpreterzustands
- Kampf- und Maniac-Patch-Befehle außerhalb der bereits benötigten
  Picture-Pointer-Konvention

## Referenzsemantik

Die Laufzeitregeln wurden gegen die Primärimplementierung von EasyRPG
abgeglichen:

- [Interpreter, Kontrollfluss, Wait und Picture-Befehle](https://raw.githubusercontent.com/EasyRPG/Player/master/src/game_interpreter.cpp)
- [Picture-Zustand, Dauer und Interpolation](https://raw.githubusercontent.com/EasyRPG/Player/master/src/game_pictures.cpp)
- [ControlVariables-Charakterwerte](https://raw.githubusercontent.com/EasyRPG/Player/master/src/game_interpreter_control_variables.cpp)
