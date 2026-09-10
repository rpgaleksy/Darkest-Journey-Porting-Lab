# Picture-Zustand in Darkest Journey

## Ergebnis

Pictures sind keine statischen Map-Ebenen. Sie bilden einen globalen,
zustandsbehafteten Registersatz, der nach Bild-ID adressiert wird:

- `ShowPicture` ersetzt den Zustand einer Bild-ID vollständig.
- `MovePicture` setzt Zielwerte für ein bereits gezeigtes Bild und interpoliert
  Position, Zoom, Farbton und Transparenz über eine Dauer.
- `ErasePicture` leert die Bild-ID.
- Eine höhere Bild-ID wird bei klassischen Pictures über einer niedrigeren
  Bild-ID gezeichnet.
- Ein Mapwechsel löscht klassische Pictures nicht automatisch. Die dafür
  vorgesehene `erase_on_map_change`-Flagge gehört zu neueren Erweiterungen und
  kommt in den hier untersuchten 14-Parameter-Befehlen nicht vor.

Damit gibt es ohne ausgeführten Eventpfad oder gespeicherten Spielstand kein
eindeutiges „Picture dieser Map“. Eine aktive Eventseite sagt nur, welcher
Befehlssatz ausführbar wäre; sie sagt nicht, ob und bis wohin er bereits
ausgeführt wurde.

Die Referenzsemantik ist in folgenden Primärquellen nachvollziehbar:

- [EasyRPG `game_interpreter.cpp`](https://raw.githubusercontent.com/EasyRPG/Player/master/src/game_interpreter.cpp)
- [EasyRPG `game_pictures.cpp`](https://raw.githubusercontent.com/EasyRPG/Player/master/src/game_pictures.cpp)
- [EasyRPG `sprite_picture.cpp`](https://raw.githubusercontent.com/EasyRPG/Player/master/src/sprite_picture.cpp)
- [liblcf `eventpage.h`](https://raw.githubusercontent.com/EasyRPG/liblcf/master/src/generated/lcf/rpg/eventpage.h)
- [liblcf `commonevent.h`](https://raw.githubusercontent.com/EasyRPG/liblcf/master/src/generated/lcf/rpg/commonevent.h)

## Befund im Projekt

Die Zählung umfasst alle 84 parsebaren LMU-Dateien sowie die Common Events in
`RPG_RT.ldb`:

| Bereich | Befehlslisten | `ShowPicture` | `MovePicture` | `ErasePicture` |
|---|---:|---:|---:|---:|
| Map-Events | 131 Seiten | 153 | 25 | 46 |
| Common Events | 6 Events | 24 | 4 | 8 |
| **Gesamt** | **137** | **177** | **29** | **54** |

Alle 177 Show-Befehle besitzen das klassische 14-Parameter-Format, alle 29
Move-Befehle 16 Parameter und alle 54 Erase-Befehle genau einen Parameter.
Erweiterte RPG-Maker-2003-1.12- oder Maniac-Picture-Parameter kommen in diesen
Befehlen nicht vor. Das begrenzt den ersten kompatiblen Interpreter sinnvoll
auf die klassische Semantik.

Von den 177 Show-Befehlen verwenden 114 feste Koordinaten und 63
Variablenkoordinaten. 39 Bilder sind an die Map gebunden, 138 an den
Bildschirm. Bei `effect_mode == 0` enthalten einige ungenutzte
`effect_power`-Felder beliebige Werte; EasyRPG ignoriert sie ebenfalls und
setzt die effektive Stärke auf null.

### Verwendungsarten

| Klasse | Seiten/Events | Typisches Verhalten |
|---|---:|---|
| Einmalige Map-Ebene | 39 Seiten auf 36 Maps | Paralleles Event zeigt Licht, Schatten oder Raum-Overlay und beendet sich mit `EraseEvent`. Das Bild bleibt bestehen. |
| Paralleler Laufzeiteffekt | 6 Seiten auf 6 Maps | Wiederholtes Anzeigen oder Bewegen, etwa Nebel, Herzschlag und wechselnde Beleuchtung. |
| Spielerinteraktion | 80 Seiten auf 26 Maps | Dokumente, Tag-Einblendungen, Türen und Taschenlampenlogik; häufig mit Verzweigungen. |
| Autorun/Zwischensequenz | 6 Seiten auf 5 Maps | Introtafeln, Zugfahrten und Titelbilder mit zeitabhängigen Show/Move/Erase-Folgen. |
| Paralleles Common Event | 3 Events | Taschenlampe, alter Filmeffekt und Menü-Steuerung. |
| Aufgerufenes Common Event | 3 Events | Dynamische Menübilder und Notizansichten. |

Das erklärt auch die scheinbaren „Lightmaps“: Viele davon heißen nicht
`Lightmap`, sondern beispielsweise `flur`, `büro1`, `ostseite`, `fog2` oder
`blackness`. Die aktuelle Namensprüfung kann deshalb nur den einen bereits
bekannten Sonderfall auf `Map0041` erkennen.

### Bild-IDs als Kanäle

| Roh-ID | Befund | Konsequenz |
|---:|---|---|
| 1 | 47 Shows, 33 Erases; Dokumente, Tageskarten und Zwischensequenzen | Meist kurzlebige Vollbild-Einblendung, aber nicht ausschließlich. |
| 2 | 10 Shows, 9 Erases | Zweiter Intro-/Notizkanal. |
| 3–8 | Vor allem Introelemente | Mehrere gleichzeitig sichtbare Bilder sind möglich. |
| 10–11 | Titel- und Logoüberblendungen | Reihenfolge nach ID ist sichtbar relevant. |
| 19 | 22 Shows, 6 Moves, 1 Erase | Vorwiegend Umgebungslicht, Nebel und Filmeffekt. |
| 20 | 83 Shows, 14 Moves, 5 Erases | Stark überladen: Map-Licht, Taschenlampenkegel, Herzanimation und Interaktionszustände. |
| 50113 | 6 Shows | Picture-Pointer-Patch: tatsächliche ID aus Variable 113, vierstelliger Dateisuffix aus Variable 114. |

`50113` darf daher weder als echte Zeichenebene noch als normale Bild-ID
behandelt werden. Die im Projekt vorkommenden Namen `Item_XXXX` und
`Notiz_XXXX` werden erst zur Laufzeit zu Namen wie `Item_0019` aufgelöst.

### Wichtige Variablenabhängigkeiten

Die Variablenkoordinaten gruppieren sich vollständig in fünf Paare:

| Variablen | Show-Anzahl | Verwendung |
|---|---:|---|
| 41 / 42 | 43 | Taschenlampen- und Sichtkegelposition |
| 48 / 49 | 7 | Herzposition; zusätzlich 10 Move-Befehle |
| 30 / 31 | 6 | Mapgebundene Licht-/Nebelebenen |
| 45 / 46 | 5 | Ventilatorgrafiken |
| 50 / 51 | 2 | Weitere mapgebundene Objekte |

Die Rohwerte negativer Koordinaten erscheinen im LCF-Datenstrom als
32-Bit-Werte, etwa `4294967146` für `-150`. Ein Picture-Decoder muss diese
positionsbezogenen Parameter als vorzeichenbehaftete 32-Bit-Zahlen
normalisieren. Der bestehende Lightmap-Renderer tut dies bereits lokal.

## Festgelegtes Vorschau-Modell

Der Renderer soll nicht alle `ShowPicture`-Befehle aktiver Eventseiten
gleichzeitig zeichnen. Stattdessen wird die Picture-Unterstützung in drei
Schichten aufgebaut:

1. Ein `PictureState`-Register hält den aktuellen Zustand pro aufgelöster
   Bild-ID. Es implementiert Show, Move und Erase unabhängig vom Renderer.
2. Ein expliziter Event-Trace spielt ausgewählte Befehlslisten bis zu einem
   definierten Befehl oder Zeitpunkt ab. Verzweigungen werden nur mit einem
   angegebenen Switch-/Variablenzustand verfolgt.
3. Ein Vorschauprofil kann mit einem leeren oder ausdrücklich vorgegebenen
   Anfangsregister starten und konkrete Traces hinzufügen. Eine spätere
   LSD-Unterstützung kann dasselbe Register direkt aus einem Spielstand
   initialisieren.

Für eine einfache Map-Einstiegsvorschau darf zusätzlich eine konservative
Abkürzung angeboten werden: aktive parallele Seiten, die nach dem Anzeigen
einer Map-Ebene mit `EraseEvent` enden, können als einmalige Setup-Traces
ausgeführt werden. Seiten mit Schleifen, Spielerinteraktion oder nicht
auflösbaren Verzweigungen werden nicht stillschweigend simuliert.

## Implementierter erster Slice

Der erste Slice ist im statischen Renderer umgesetzt:

- `03_rendering/picture_state.py` hält einen Picture-Slot pro aufgelöster
  Bild-ID und verarbeitet klassische `ShowPicture`-, `MovePicture`- und
  `ErasePicture`-Befehle.
- Variable Koordinaten werden aus dem expliziten Vorschauzustand gelesen.
  Map-Event-Koordinaten für `ControlVariables` folgen der klassischen
  16×16-Tile-Geometrie: X liegt in der Sprite-Mitte, Y an der Sprite-Basis.
- `ControlSwitches` verwendet die originale Befehlswert-Semantik:
  0 schaltet an, 1 schaltet aus und 2 schaltet den bisherigen Wert um.
- Die projektweite Picture-Pointer-ID `50113` löst die tatsächliche Bild-ID
  aus Variable 113 und den vierstelligen Namenssuffix aus Variable 114 auf.
- `render_map.py --pictures` führt nur ausgewählte parallele Map-Setup-Seiten
  aus, die mit `EraseEvent` enden und ausschließlich konservativ erlaubte
  Befehle enthalten. Das Ergebnis wird als fertiger statischer Slot-Zustand
  gerendert und im Manifest diagnostisch protokolliert.
- `--lightmap` verwendet denselben Registerpfad und behält zusätzlich einen
  direkten Lightmap-Fallback für ältere, nicht-parallele Testfälle bei.

Damit sind die Akzeptanzfälle `Map0041` (Variable 56 = 1) und `Map0010` als
echte Originaldaten geprüft. Common Events und interaktive beziehungsweise
zeitabhängige Picture-Folgen bleiben bewusst außerhalb dieses ersten Slices.

### Semantik des Registers

- Show löst zuerst konstante oder variable Koordinaten sowie gegebenenfalls
  Picture Pointer auf und ersetzt danach den kompletten Slot.
- Move ohne existierendes Bild verändert keinen sichtbaren Inhalt. Für eine
  Momentaufnahme müssen Startzustand, Zielzustand und verbleibende Dauer
  getrennt erhalten bleiben.
- Bei einem wartenden Move schreitet der Trace um dessen Dauer fort. Ein
  nicht wartender Move bleibt bis zu einem ausdrücklich gewählten Zeitpunkt
  in Bewegung.
- Erase leert den aufgelösten Slot, ohne andere IDs zu beeinflussen.
- Gezeichnet wird nach aufsteigender Bild-ID. Bildschirmgebundene Bilder
  verwenden die 320×240-Koordinaten direkt; mapgebundene Bilder werden um die
  Kamera-/Scrollposition versetzt.
- Transparenz, Zoom, Farbton und die transparente Palette-0-Farbe gehören zum
  Slotzustand. Ein bedeutungsloses Effektstärkefeld bei Effektmodus null wird
  ignoriert.

## Akzeptanzfälle für die Implementierung

1. `Map0041`, Variable 56 = 1: Das einmalige Setup zeigt
   `Lightmap_(diagonal_links_oben)` auf ID 19 und beendet nur das Map-Event.
2. `Map0010`: Das einmalige Setup zeigt `flur` mapgebunden auf ID 20, obwohl
   der Dateiname kein `lightmap` enthält.
3. Common Event 3 (`Taschenlampe`): Richtung und Variablen 41/42 wählen und
   positionieren genau einen Sichtkegel auf ID 20.
4. `Map0002`: `train` startet mit negativer X-Position, bewegt sich über einen
   wartenden Move und wird später wieder gelöscht.
5. Common Events 13/14: Roh-ID 50113 wird über Variablen 113/114 in eine echte
   ID und einen vorhandenen Menübildnamen aufgelöst.
6. `Map0064`: Die Herzsequenz ersetzt und bewegt ID 20 wiederholt, ohne sechs
   Herzbilder gleichzeitig zu erzeugen.

## Bewusst vertagt

- vollständige Scheduler-Semantik für parallel laufende Events
- Message-, Eingabe- und Kampfabläufe innerhalb beliebiger Traces
- Rotation und Wellenanimation als bewegte Ausgabe
- Rekonstruktion eines historischen Spielverlaufs ohne LSD-Spielstand
- erweiterte Picture-Befehle neuerer RPG-Maker-Versionen und Maniac Patch
