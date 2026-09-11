# Interaktiver macOS-Diagnosehost

## Entscheidung

Der erste interaktive Host wird als dünne Python-/Tk-Schicht aufgebaut. Die
Spielsemantik bleibt vollständig in den plattformneutralen Parser-, Runtime-
und Renderer-Modulen. Tk übernimmt ausschließlich Fenster, Tastaturereignisse,
Frame-Timer und die Darstellung eines fertigen Szenen-Snapshots.

Diese Wahl ist ein Portierungsnachweis, keine Festlegung für eine spätere
Release-Oberfläche. Auf der geprüften ARM-Mac-Umgebung sind Python 3.12.4 und
Tk 8.6.14 bereits lauffähig. Dadurch kann der erste Host ohne neue Abhängigkeit
im selben Prozess wie der vorhandene Python-Interpreter arbeiten. Swift/AppKit
bleibt eine spätere native Hülle; SDL2 oder eine vergleichbare Laufzeit bleibt
eine Option, sobald Bildrate, Audio, Gamepads und Distribution wichtiger als
die schnelle Kompatibilitätsprüfung werden.

Der Host erhält zunächst keinen Produktnamen, keine Bundle-ID und keine
Version. Das Lab ist weiterhin explorativ; ein Fensterprototyp ist noch kein
distributierbares Spiel.

## Warum die Provider-Schnittstelle zuerst erweitert werden muss

`runtime_providers.py` kann bereits vollständig vorgegebene Entscheidungen
anwenden. Das reicht für Tests und reproduzierbare Traces, aber noch nicht für
eine Live-Oberfläche: `awaiting_input` beendet eine `TraceSession`, während ein
echtes Nachrichtenfenster oder wartendes `KeyInputProc` über beliebig viele
Frames pausieren und danach an derselben Stelle fortsetzen muss.

Die EasyRPG-Referenz bestätigt drei unterschiedliche Lebenszyklen:

- `ShowMessage` sammelt unmittelbar folgende `ShowMessage_2`-Zeilen in einem
  Nachrichtenauftrag. Der Interpreterindex zeigt danach bereits auf den
  folgenden Befehl, während ein eigener Message-Zustand den Interpreter bis
  zum Schließen des Fensters anhält.
- Ein wartendes `KeyInputProc` installiert einen Eingabezustand, setzt seine
  Zielvariable zunächst auf `0` und wartet mindestens einen Frame. Erst ein
  erlaubter Triggerwert löst den Zustand und gibt den nächsten Befehl frei.
- `MoveEvent` startet eine Route ohne selbst zu warten.
  `ProceedWithMovement` hält anschließend den Interpreter an, solange irgendwo
  eine erzwungene Bewegungsroute aktiv ist.

Ein bloßes Wiederholen desselben Eventbefehls pro Frame wäre ungeeignet: Es
könnte ein Nachrichtenfenster oder eine Route mehrfach starten und würde die
Seiteneffekte des Befehls mit seinem späteren Abschluss vermischen.

## Provider- und Session-Zustand

Der nächste Runtime-Slice ergänzt daher einen ausdrücklich gespeicherten
externen Wait. Die Begriffe erhalten folgende Bedeutung:

| Status | Bedeutung | Session terminal |
|---|---|---:|
| `completed` | Auftrag wurde vollständig beantwortet | nein |
| `pending` | Auftrag wurde genau einmal angenommen und wird später gepollt | nein |
| `awaiting_input` | kein Live-Anbieter oder keine Antwortquelle vorhanden | ja |
| `unsupported` | Anbieter unterstützt die angeforderte Semantik nicht | ja |
| `invalid_data` | Befehl oder Anbieterantwort ist ungültig | ja |

Eine `ProviderRequest` erhält eine stabile ID, Diensttyp, Quelle,
Befehlsindex, Startframe und den normalisierten Payload. Bei `pending` speichert
die `TraceSession` einen `ExternalWait` mit dieser Request-ID. Zu Beginn jedes
späteren Scheduler-Slots fragt sie denselben Provider mit `poll(request, ... )`
ab. Erst `completed` wendet Rückgabewerte an und lässt die Session mit dem
bereits folgenden Eventbefehl weiterlaufen.

Wird ein Task durch Seitenwechsel, `EraseEvent`, strikten Abbruch oder das
dauerhafte Ende seines Lebenszyklus beendet, wird auch sein offener Request
abgemeldet. Eine bloße Pause durch einen ausgeschalteten Aktivierungsswitch
behält den Request dagegen bei. Damit kann kein altes Nachrichtenfenster
später den Zustand einer neuen Map-Seite verändern, ohne dass eine pausierte
Parallel-Session ihre legitime Antwort verliert.

Der synchrone `EventTraceRunner.run()` bleibt eine Diagnoseschnittstelle. Ein
Live-Provider darf dort einen `pending`-Zustand als sichtbares
`awaiting_input`-Ergebnis zurückgeben; dauerhaftes Polling ist Aufgabe von
`TraceSession` und Scheduler.

## Nachrichten

Der Interpreter erzeugt einen Auftrag pro Nachrichtenblock, nicht pro Zeile.
Ein Block beginnt mit `ShowMessage` und enthält alle direkt folgenden
`ShowMessage_2`-Kommandos. Der Provider erhält die Zeilen getrennt sowie die
gemeinsame Quelle; Choices bleiben zunächst außerhalb des Blocks.

Die Originaldaten enthalten projektweit 1.554 `ShowMessage`- und 1.537
Fortsetzungszeilen. Für den ersten Host sind folgende tatsächlich verwendete
Steuercodes relevant:

| Code | Vorkommen | erster Host |
|---|---:|---|
| `\C[n]` | 576 | Textfarbe wechseln |
| `\V[n]` | 4 | Variablenwert einsetzen |
| `\|` | 219 | zeitgesteuerte Pause |
| `\!` | 204 | zusätzliche Bestätigung abwarten |
| `\^` | 16 | Block ohne Schlussbestätigung schließen |

Unbekannte Steuercodes werden sichtbar protokolliert und nicht still
entfernt. Ein späterer Text-Layout-Slice muss außerdem Face-Grafiken,
Nachrichtenposition, Transparenz und exakte RPG-Maker-Schriftmetriken
berücksichtigen.

## Tastatur

Darkest Journey verwendet nur acht `KeyInputProc`-Befehle und ausschließlich
die klassische fünfparametrige RPG-Maker-2003-Form. Der erste Decoder kann
deshalb eng bleiben:

- Parameter 0 ist die Zielvariable, Parameter 1 das Wait-Flag.
- Parameter 2 aktiviert alle Richtungen, Parameter 3 Entscheidung und
  Parameter 4 Abbruch.
- Die Rückgabewerte sind `1` unten, `2` links, `3` rechts, `4` oben, `5`
  Entscheidung und `6` Abbruch.
- Wartende Abfragen verwenden Triggerereignisse und warten mindestens einen
  Frame; nicht wartende Abfragen lesen den gehaltenen Zustand und dürfen `0`
  liefern.

Tk-Ereignisse werden zuerst in ein plattformneutrales `InputFrame` mit
`pressed`- und `triggered`-Mengen übersetzt. UI-Callbacks schreiben niemals
direkt in Switches, Variablen oder Charakterzustände. Eine getestete
Standardbelegung ist Pfeiltasten für Richtungen, Return/Space/Z für
Entscheidung und X/Backspace für Abbruch. Escape bleibt ausschließlich dem
Beenden des Diagnosehosts vorbehalten.

## Bewegung

Die Originaldaten enthalten 811 `MoveEvent`- und 751
`ProceedWithMovement`-Befehle. Bewegung ist deshalb kein kleiner Zusatz zum
Fensterhost, sondern ein eigener Runtime-Slice.

Der Bewegungsanbieter wird global einmal pro Frame fortgeschrieben und hält
pro Charakter Route, Befehlsindex, Frequenz, Wiederholung, Skippable-Flag,
Restdistanz und Ergebnis. `MoveEvent` legt diesen Zustand an;
`ProceedWithMovement` beobachtet ihn über einen externen Wait. Kollision,
Map-Looping und fehlgeschlagene nicht-skippable Schritte dürfen nicht durch
sofortige Koordinatenänderungen ersetzt werden.

Der erste sichtbare Host darf Bewegungsbefehle daher noch mit
`unsupported` melden. Sein Vertrag und seine Cancellation-Semantik müssen
aber bereits zum späteren globalen Route-Tick passen.

## Frame- und Host-Architektur

```text
Tk key events ──> InputFrame ──> InteractiveRuntime.tick()
                                      │
                                      ├─ offene Provider-Requests pollen
                                      ├─ Interpreter/Scheduler fortsetzen
                                      ├─ globale Dienste einmal fortschreiben
                                      └─ SceneSnapshot erzeugen
                                                     │
cached map/assets ──> SceneRenderer <────────────────┘
                            │
                            └─> Tk canvas + message overlay
```

Der Tk-Timer verwendet eine monotone Uhr und einen Akkumulator. Spielzustand
wird ausschließlich in ganzzahligen Frames verändert. Falls die Oberfläche
hinterherhinkt, darf der Host nur eine begrenzte Zahl Frames nachholen und
muss verworfene Frames diagnostisch zählen; er darf nicht mehrere Provider-
oder Picture-Updates als einen undokumentierten Zeitsprung behandeln.

Parsergebnisse und statische Map-Ebenen werden einmal beim Szenenstart
geladen. Ein lokaler Testlauf für Map0002 benötigte für den vollständigen
statischen Renderpfad ungefähr 1,25 Sekunden; ein erneutes Parsen und
Komponieren in jedem 60-Hz-Frame ist damit ausgeschlossen. Der erste Host
verwendet ein gecachtes Hintergrundbild. Bewegte Charaktere, Pictures und
Kamera-Ausschnitt werden anschließend als getrennte dynamische Ebenen
entwickelt.

`InteractiveRuntime` bleibt ohne Tk importierbar und erhält ausschließlich
Input-Frames, Providerantworten und einen Frame-Aufruf. So können alle
Lebenszyklen headless getestet und eine spätere AppKit-/SDL-Hülle ohne zweite
Spielsemantik ergänzt werden.

## Erster sichtbarer Abnahmefall

Der erste Fensterprototyp verwendet Originaldaten read-only, aber noch keinen
vollständigen Spielstart:

1. Map0002 wird einmal als gecachter Hintergrund geladen und in einem
   320×240-Viewport mit ganzzahliger Skalierung dargestellt.
2. Event 15, Seite 0, wird als explizites Segment `[14, 21)` gestartet.
3. Die drei Paul-Zeilen und die drei Eileen-Zeilen werden jeweils als ein
   Nachrichtenblock angezeigt und mit Entscheidungstasten fortgesetzt.
4. Nach dem zweiten Block wird der folgende `PlaySound`-Befehl weiterhin nur
   als Aktion protokolliert; der Segmentabschluss bleibt sichtbar.
5. Escape beendet ausschließlich den Diagnosehost und schreibt nichts in das
   Originalprojekt.

Dieser Fall beweist Fenster, Originaltext, Blockbildung, Live-Pause,
Wiederaufnahme und unveränderte Eventreihenfolge. Er behauptet weder einen
spielbaren Startbildschirm noch korrekte Bewegung, Kollision oder Audio.

## Umsetzungsslices

### A – resumierbare Live-Requests

- `ProviderRequest`, `pending` und `ExternalWait` ergänzen.
- Message-Fortsetzungszeilen zu einem Auftrag zusammenfassen.
- klassische fünfparametrige Key-Input-Maske dekodieren.
- Polling, Mindestwarteframe, Completion und Cancellation headless testen.
- bestehende Scripted-Provider und synchrone Traces kompatibel halten.

### B – Headless-Controller und Tk-Hülle

- plattformneutrales `InputFrame` und `InteractiveRuntime.tick()` bauen.
- statischen Map-Hintergrund einmal laden und im Viewport cachen.
- Tk-Fenster, ganzzahlige Skalierung, Eingabebelegung und Message-Overlay
  ergänzen.
- den Map0002-Abnahmefall als explizites Startprofil bereitstellen.

### C – Bewegung und dynamische Szene

- Move-Route-Bytefolge konservativ dekodieren und verwendete Opcodes erfassen.
- Route-Zustand, Frequenz, Restdistanz und globalen Movement-Tick implementieren.
- Passierbarkeit und Kollision aus Chipset-/Mapdaten anbinden.
- Charaktere, Kamera und Pictures aus `SceneSnapshot` dynamisch rendern.

### D – Spielablauf

- Vordergrund-, Autorun-, Berührungs- und Action-Key-Dispatcher ergänzen.
- Choices, Teleports, Karteninstanzen und persistente Zustände integrieren.
- Audio und weitere Bildschirmbefehle über austauschbare Dienste anbinden.

## Ablage und Grenzen

Plattformneutrale Controller- und Providerlogik bleibt in `05_runtime/`.
Die dünne Tk-/macOS-Hülle erhält einen getrennten Bereich `07_macos_host/`.
Generierte Bilder, Caches und Diagnosezustände gehen nur in ausdrücklich
angegebene Lab- oder `/private/tmp`-Ziele. Originalspiel und RTP bleiben
außerhalb des Repositories und read-only.

Bewusst vertagt bleiben ein App-Bundle, Code Signing, Installer, Release-
Version, endgültiger Produktname, native Swift-Hülle, Gamepadunterstützung und
Performanceoptimierung jenseits des ersten gecachten Viewports.

## Referenzen

- [EasyRPG Interpreter: Update-, Message-, Movement- und Key-Input-Semantik](https://raw.githubusercontent.com/EasyRPG/Player/master/src/game_interpreter.cpp)
- [EasyRPG Character: Route- und Framefortschritt](https://raw.githubusercontent.com/EasyRPG/Player/master/src/game_character.cpp)
- [Python-Dokumentation zu Tkinter](https://docs.python.org/3/library/tkinter.html)
