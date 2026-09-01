# Darkest Journey – LDB/LMT/LMU-Parserlauf

## Lauf

- Quelle: das unveränderte Originalprojekt außerhalb des Porting Labs
- Parser: `02_parsing/parse_project.py`
- Auswahl: `RPG_RT.ldb`, `RPG_RT.lmt` und `Map0001.lmu`
- Ausgabe: `parser-map0001.json`
- Schreibmodus: read-only

## Ergebnis

- Datenbank-Vektoren:
  - **1** Actor (`Paul`)
  - **1** Skill
  - **50** Items, davon **23** benannt
  - **1** Enemy und **1** Troop-Datensatz
  - **1** Terrain, **1** Attribute- und **1** State-Datensatz
  - **2** Battle-Animationen (`KilledbyIrontwister`, `Firestorm`)
  - **12** Chipsets, darunter `Subway`, `Büros und Klos`, `Gänge` und `Ruine`
  - **300** Switches und **200** Variables
  - **30** Common Events, davon **20** benannt, mit insgesamt **1.130**
    dekodierten Event-Kommandos
- Systemdaten: Titelgrafik `Title`, Gameover-Grafik `gameover`, Systemgrafik
  `systemskin`; die Fahrzeugnamen verweisen auf `bloody`
- Terms: unter anderem `" erscheint!"`, `" Ihr habt den Kampf gewonnen!"`,
  `GM`, `Ja` und `Nein`
- Map-Baum: **85** Einträge
- Map: **20 × 15** Tiles; beide Dimensionen wurden als RPG-Maker-Standardwert
  ergänzt, weil sie in `Map0001.lmu` nicht explizit gespeichert sind
- Tile-Layer: **300** Werte im unteren und **300** Werte im oberen Layer
- Events: **2**
  - `Eileen` bei `(11, 7)`
  - `Sequenz`
- Event-Kommandos: **83** im aktiven Page-Inhalt des ausgewählten Maps
- Unbekannte LDB-Root-Chunks: **0**
- Vier komplexe Animationsfelder (Timings/Frames) bleiben als unbekannte
  Record-Chunks mit Hash und Hex-Vorschau dokumentiert
- LDB-Dekodierfehler und -Warnungen: **0**
- LMU-Top-Level-Dekodierfehler und -Warnungen: **0**

## Einordnung

Der Export ist bereits eine belastbare Grundlage für weitere Offline-Schritte:
Map-Layer können später gerendert, Event-Kommandos nach Code analysiert,
Common Events mit Map-Events verknüpft und Ressourcenreferenzen gegen das RTP
abgeglichen werden.

Noch bewusst nur strukturell erfasst werden einige komplexe LDB-Arrays, etwa
Enemy-Actions, Troop-Seiten und Animationsframes, außerdem Musik-/Encounter-
Vektoren und Bewegungsrouten in Maps. Diese Bereiche bleiben als gezählte
Rohpayloads nachvollziehbar erhalten.
