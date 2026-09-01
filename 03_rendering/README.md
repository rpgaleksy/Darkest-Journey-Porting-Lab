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

Zusätzlich wählt der Renderer pro Map-Event die höchstrangige Seite aus, deren
Switch- und Variablenbedingungen im angegebenen Vorschauzustand erfüllt sind.
Nur das Charset dieser aktiven Seite wird als statisches Sprite eingeblendet.
Die Manifestdatei hält Auflösung, Tile-Statistik, Zustandswerte, jede geprüfte
Seitenauswahl, Sprite-Auflösung und bekannte Grenzen fest.

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

## Bewusste Grenzen des ersten Prototyps

Die Vorschau ist eine Diagnoseansicht und kein Ersatz für die Laufzeit. Noch
nicht ausgewertet werden:

- Laufzeit-Tile-Substitutionsbefehle
- Passierbarkeitsbasierte Ebenen-/Z-Reihenfolge
- animierte Autotile-Frames; verwendet wird deterministisch Frame 0
- übrige Pictures außerhalb von `--lightmap`, Panoramen, Bildschirm-Tönungen
  und der übrige Laufzeitzustand
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
