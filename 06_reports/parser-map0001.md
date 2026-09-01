# Darkest Journey – erster LCF-Parserlauf

## Lauf

- Quelle: das unveränderte Originalprojekt außerhalb des Porting Labs
- Parser: `02_parsing/parse_project.py`
- Auswahl: `RPG_RT.lmt` und `Map0001.lmu`
- Ausgabe: `parser-map0001.json`
- Schreibmodus: read-only

## Ergebnis

- Map-Baum: **85** Einträge
- Map: **20 × 15** Tiles; beide Dimensionen wurden als RPG-Maker-Standardwert
  ergänzt, weil sie in `Map0001.lmu` nicht explizit gespeichert sind
- Tile-Layer: **300** Werte im unteren und **300** Werte im oberen Layer
- Events: **2**
  - `Eileen` bei `(11, 7)`
  - `Sequenz`
- Event-Kommandos: **83** im aktiven Page-Inhalt des ausgewählten Maps
- Unbekannte Top-Level-Chunks: **0**
- Top-Level-Dekodierfehler: **0**
- Top-Level-Warnungen: **0**

## Einordnung

Der Export ist bereits eine belastbare Grundlage für weitere Offline-Schritte:
Map-Layer können später gerendert, Event-Kommandos nach Code analysiert und
Ressourcenreferenzen gegen das RTP abgeglichen werden.

Noch bewusst nur strukturell erfasst werden Musik-/Encounter-Vektoren und
Bewegungsrouten. `RPG_RT.ldb`, der Durchlauf über alle Maps und die
Ressourcenauflösung sind die nächsten Parser-Ausbaustufen.
