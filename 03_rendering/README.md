# 03 – Rendering

## Statische Map-Vorschau

`render_map.py` erzeugt aus einer read-only gelesenen `Map*.lmu`, der LDB und
den vorhandenen Projektressourcen eine PNG-Vorschau sowie eine JSON-Manifestdatei.
Die Ausgabe wird ausschließlich an den ausdrücklich angegebenen Zielpfad
geschrieben; das Originalprojekt wird nicht verändert und keine Originalressource
wird in das Repository kopiert.

Beispiel:

```text
PYTHONDONTWRITEBYTECODE=1 python3 03_rendering/render_map.py \
  "/Users/aleksl/Library/CloudStorage/Dropbox/CODING PRODUCTION/ChatGPT Codex Experiments/Darkest Journey" \
  --map Map0014.lmu \
  --scale 2 \
  --out /private/tmp/darkest-journey-map0014.png
```

Der Renderer verwendet nur die Python-Standardbibliothek. Er dekodiert die im
Spiel verwendeten 8-Bit-PNGs, behandelt bei Chipsets und Charsets den
Palettenindex 0 als transparent und rekonstruiert die bekannten Chipset-Blöcke
A–F auf 16×16-Tiles. Bei Pictures entscheidet dagegen der jeweilige
`ShowPicture`-Command über die Palette-0-Transparenz. Die Blockgrenzen und die
Autotile-Quadranten sind an der öffentlichen EasyRPG-Referenz ausgerichtet:

- [EasyRPG `map_data.h`](https://raw.githubusercontent.com/EasyRPG/Player/master/src/map_data.h)
- [EasyRPG `tilemap_layer.cpp`](https://raw.githubusercontent.com/EasyRPG/Player/master/src/tilemap_layer.cpp)

Fehlt das Chipset-Feld in einer LMU, verwendet der Parser wie `liblcf` den
RPG-Maker-Standardwert 1 und protokolliert diesen Default im Manifest. Ein
vorhandener Datenbankeintrag ohne Bildnamen ist dagegen ein gültiges leeres
Chipset: Analog zu EasyRPG wird dafür ein transparentes 480×256-Raster erzeugt.
Damit bleiben absichtlich schwarze Steuerungs- und Übergangs-Maps renderbar,
ohne eine nicht vorhandene Ressourcendatei zu erfinden.

- [liblcf `rpg::Map`](https://github.com/EasyRPG/liblcf/blob/master/src/generated/lcf/rpg/map.h)
- [EasyRPG `spriteset_map.cpp`](https://raw.githubusercontent.com/EasyRPG/Player/master/src/spriteset_map.cpp)

Zusätzlich wählt der Renderer pro Map-Event die höchstrangige Seite aus, deren
Switch- und Variablenbedingungen im angegebenen Vorschauzustand erfüllt sind.
Nur das Charset dieser aktiven Seite wird als statisches Sprite eingeblendet.
Die Manifestdatei hält Auflösung, Tile-Statistik, Zustandswerte, jede geprüfte
Seitenauswahl, Sprite-Auflösung und bekannte Grenzen fest.

Ein in der Map gespeichertes Panorama wird als initialer Hintergrund hinter den
Tile-Layern eingeblendet. Die Vorschau übernimmt dabei die gespeicherten
Horizontal-/Vertikal-Schleifen; sie simuliert weder automatische Laufzeit-
Bewegung noch `Change Parallax BG`-Befehle. In `Darkest Journey` betrifft das
aktuell `Map0059` (`bloody`) und `Map0067` (`abfahrt`).

Nicht ausdrücklich gesetzte Switches gelten als `off`, nicht gesetzte
Variablen als `0`. Abweichende Werte können wiederholt angegeben werden; bei
doppelten IDs gilt der letzte Wert:

```text
--switch 55=on --switch 4=off --variable 56=1
```

Die Variablenvergleiche folgen den RPG-Maker-2003-Operatoren `==`, `>=`,
`<=`, `>`, `<` und `!=`. `Darkest Journey` verwendet in seinen 2.523
Eventseiten ausschließlich Switch-A, Switch-B und Variablenbedingungen; die
aktuelle Auswertung deckt damit alle im Spiel vorhandenen Eventseiten-
Bedingungsarten ab. Seiten werden wie in RPG Maker von der letzten zur ersten
geprüft. Die Semantik ist an der öffentlichen EasyRPG-Referenz ausgerichtet:

- [EasyRPG `game_event.cpp`](https://raw.githubusercontent.com/EasyRPG/Player/master/src/game_event.cpp)
- [EasyRPG `game_interpreter_shared.h`](https://raw.githubusercontent.com/EasyRPG/Player/master/src/game_interpreter_shared.h)
- [EasyRPG `game_switches.h`](https://raw.githubusercontent.com/EasyRPG/Player/master/src/game_switches.h)
- [EasyRPG `game_variables.h`](https://raw.githubusercontent.com/EasyRPG/Player/master/src/game_variables.h)

Für die erkannte Lightmap-Ebene kann zusätzlich `--lightmap` verwendet werden:

```text
PYTHONDONTWRITEBYTECODE=1 python3 03_rendering/render_map.py \
  "/Users/aleksl/Library/CloudStorage/Dropbox/CODING PRODUCTION/ChatGPT Codex Experiments/Darkest Journey" \
  --map Map0041.lmu \
  --scale 2 \
  --variable 56=1 \
  --lightmap \
  --out /private/tmp/darkest-journey-map0041-state-lightmap.png
```

Der Schalter berücksichtigt `ShowPicture`-Befehle der aktiven Eventseiten,
deren Bildname `lightmap` enthält. Die Position wird als Mittelpunkt in der
320×240-RPG-Maker-Koordinatenfläche interpretiert, der Zoom per
Nearest-Neighbor umgesetzt und die im Command gesetzte Transparenz angewendet.
Ob ein Bild im Spiel als transparent geladen wird, folgt dabei ebenfalls dem
Command-Feld für die transparente Farbe. Bei `Map0041` aktiviert Variable 56
mit Wert 1 sowohl die leeren Seiten der Regen-Events als auch die Lightmap-
Seite. Das entfernt die roten Diagnoseblöcke aus `regentropfen.png` und ergibt
eine 320×240-Lightmap bei `(160,120)` mit 80 % Transparenz.

Die Zuordnung der Picture-Parameter und die Mittelpunkt-Positionierung sind an
der öffentlichen EasyRPG-Referenz ausgerichtet:

- [EasyRPG `game_interpreter.cpp`](https://raw.githubusercontent.com/EasyRPG/Player/master/src/game_interpreter.cpp)
- [EasyRPG `sprite_picture.cpp`](https://raw.githubusercontent.com/EasyRPG/Player/master/src/sprite_picture.cpp)

Die projektweite Analyse zeigt, dass allgemeine Pictures als globaler
Laufzeitzustand nach Bild-ID behandelt werden müssen und nicht als Sammlung
statischer Map-Ebenen. Das daraus abgeleitete Register- und Trace-Modell ist in
[Picture-Zustand in Darkest Journey](../04_compatibility/picture-state.md)
festgehalten.

## Reproduzierbarer Vorschau-Batch

`render_batch.py` wählt standardmäßig sieben repräsentative Maps nach
reproduzierbaren Kriterien aus: die in `RPG_RT.lmt` hinterlegte Startkarte,
größte Fläche, höchste Eventdichte, höchste Dichte bedingter Seiten, die
meisten Picture-Commands, eine Lightmap-Karte und die höchste Karte. Doppelte
Treffer werden nur einmal gerendert. Mit `--map` können Karten explizit
angegeben werden, `--all-maps` rendert dagegen jede parsebare Map.

Benannte Zustände liegen in einer kleinen JSON-Profildatei. Ein Profil kann
Switches und Variablen überschreiben, die Lightmap-Ebene aktivieren und sich
optional auf bestimmte Maps beschränken. Das Repository enthält das erste
projektspezifische Beispiel in `03_rendering/representative_profiles.json`:

```text
PYTHONDONTWRITEBYTECODE=1 python3 03_rendering/render_batch.py \
  "/Users/aleksl/Library/CloudStorage/Dropbox/CODING PRODUCTION/ChatGPT Codex Experiments/Darkest Journey" \
  --profile-file 03_rendering/representative_profiles.json \
  --scale 2 \
  --out-dir /private/tmp/darkest-journey-preview-batch
```

Der Lauf schreibt pro Map/Profil-Kombination eine PNG- und eine JSON-Datei,
`batch-manifest.json` mit Auswahlmetriken und Zusammenfassung sowie eine
lokale `index.html`-Galerie. Die Ausgabe muss außerhalb des Originalprojekts
liegen. Das Profil `map0041-lightmap` setzt Variable 56 nur für
`Map0041.lmu` auf 1; der bekannte Lightmap-Zustand bleibt damit explizit und
wird nicht stillschweigend auf fremde Maps angewendet.

Wenn eine ausgewählte Map kein auflösbares Chipset besitzt oder ein anderes
Renderer-Problem auftritt, bleibt der Batch-Lauf bei den übrigen Karten und
trägt den Fehler als `status: "error"` im Gesamtmanifest und in der Galerie
ein. Dadurch gehen Diagnosefälle nicht verloren und werden nicht als gültige
Vorschau ausgegeben.

## Bewusste Grenzen des ersten Prototyps

Die Vorschau ist eine Diagnoseansicht und kein Ersatz für die Laufzeit. Noch
nicht ausgewertet werden:

- Laufzeit-Tile-Substitutionsbefehle
- Passierbarkeitsbasierte Ebenen-/Z-Reihenfolge
- animierte Autotile-Frames; verwendet wird deterministisch Frame 0
- übrige Pictures außerhalb von `--lightmap`, dynamische
  `Change Parallax BG`-Befehle, Bildschirm-Tönungen und der übrige
  Laufzeitzustand
- Item-, Actor-, Timer- und unbekannte Eventseitenbedingungen; sie kommen in
  den aktuellen `Darkest Journey`-Maps nicht vor und werden als mehrdeutig
  protokolliert, falls sie später auftauchen

Mit `--lightmap` werden weiterhin keine `MovePicture`-Folgezustände oder
Picture-Töne/Effekte simuliert. Der ausdrücklich angegebene Vorschauzustand
ist daher eine reproduzierbare statische Annäherung und keine vollständige
Laufzeitaufnahme oder automatisch aus einem Spielstand gelesene Situation.

Diese Grenzen stehen ebenfalls im JSON-Manifest, damit spätere Renderer- oder
Kompatibilitätsprüfungen die Vorschau nicht versehentlich als pixelgenaue
Laufzeitsimulation interpretieren.
