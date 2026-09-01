# 02 – Parsing

Ziel ist ein verlässlicher, plattformunabhängiger Zugriff auf `RPG_RT.ldb`,
`RPG_RT.lmt`, `Map*.lmu` und später gegebenenfalls `LSD`-Spielstände.

## Erster Parser-Meilenstein

Der erste eigene Reader arbeitet vollständig mit der Python-Standardbibliothek
und ist read-only. Er verändert weder das Quellprojekt noch die gelesenen
Bytes.

- `lcf_reader.py` liest LCF-Header, komprimierte Base-128-Zahlen,
  length-prefixed Chunks und begrenzte Strukturen.
- `project_parser.py` überführt `RPG_RT.lmt` sowie eine ausgewählte
  `Map*.lmu` in ein JSON-fähiges Modell.
- `database_parser.py` überführt `RPG_RT.ldb` mit Datenbankeinträgen,
  Systemdaten und Common Events in dasselbe JSON-fähige Modell.
- `parse_project.py` ist der kombinierte Kommandozeilen-Einstiegspunkt;
  `parse_database.py` kann die LDB separat exportieren.
- Unbekannte Chunks werden mit Offset, Länge, Hash und kurzem Hex-Vorschauwert
  gemeldet. Teilbereiche, deren semantische Decodierung noch aussteht, bleiben
  ausdrücklich als Rohdaten markiert.

Bereits abgedeckt sind:

- Map-Baum, IDs, Namen, Elternbeziehungen, Startposition und Tree-Reihenfolge
- Windows-1252-Texte, einschließlich der im Projekt vorhandenen Umlaute
- Map-Dimensionen mit den RPG-Maker-Standardwerten 20 × 15, falls sie im LCF
  nicht explizit gespeichert sind
- little-endian Tile-Layer, Eventpositionen, Eventseiten und Bedingungen
- Event-Kommandos mit Code, Einrückung, Text, Parametern und bekannten
  Kommandonamen
- LDB-Vektoren für Actors, Skills, Items, Enemies, Troops, Terrains,
  Attributes, States, Animations, Chipsets, Switches, Variables und Common
  Events
- zentrale LDB-Felder für Kampfwerte, Ressourcenreferenzen, Systemnamen,
  Musik-/Sound-Einträge und Terms-Texte
- Common-Event-Kommandos mit derselben strukturierten Darstellung wie
  Map-Event-Kommandos
- explizite little-endian-Decodierung der festen RPG-Maker-Arrays, unabhängig
  von der Architektur des Hostsystems
- der LDB-Root wird korrekt als bis zum Dateiende laufende Struktur behandelt;
  die darin enthaltenen Records bleiben zero-terminiert
- strukturierte Warnungen bei abgeschnittenen oder inkonsistenten Daten

Beispiel:

```text
python3 02_parsing/parse_project.py \
  "/Users/aleksl/Library/CloudStorage/Dropbox/CODING PRODUCTION/ChatGPT Codex Experiments/Darkest Journey" \
  --map Map0001.lmu \
  --out /private/tmp/darkest-journey-parser.json
```

Für einen isolierten Datenbankexport:

```text
python3 02_parsing/parse_database.py \
  "/Users/aleksl/Library/CloudStorage/Dropbox/CODING PRODUCTION/ChatGPT Codex Experiments/Darkest Journey/RPG_RT.ldb" \
  --out /private/tmp/darkest-journey-ldb.json
```

Ohne `--out` wird das JSON auf stdout ausgegeben. Der Export enthält keine
Kopie der Originaldateien; Dateiname, Größe und SHA-256 dienen nur der
Nachvollziehbarkeit.

## Bewusste Grenzen

Komplexe LDB-Arrays wie Enemy-Actions, Troop-Seiten, Actor-Learning-Daten und
einige Animations-/Battle-Test-Strukturen werden zunächst sicher als
gezählte Rohpayloads dokumentiert. Musik-/Encounter-Vektoren in den Maps,
Ressourcen-Referenzen, alle Maps in einem Durchlauf und ein Renderer folgen als
separate Ausbaustufen.

Die Feldkennungen und Grundkodierung wurden gegen die öffentlich dokumentierte
`liblcf`-Implementierung abgeglichen:

- LCF reader: https://github.com/EasyRPG/liblcf/blob/master/src/reader_lcf.cpp
- LDB chunk definitions: https://github.com/EasyRPG/liblcf/blob/master/src/generated/lcf/ldb/chunks.h
- LDB reader: https://github.com/EasyRPG/liblcf/blob/master/src/ldb_reader.cpp
- LMT chunk definitions: https://github.com/EasyRPG/liblcf/blob/master/src/generated/lcf/lmt/chunks.h
- LMU chunk definitions: https://github.com/EasyRPG/liblcf/blob/master/src/generated/lcf/lmu/chunks.h
