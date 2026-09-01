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

Zusätzlich wird pro Map-Event die erste Seite mit einem nichtleeren Charset-
Namen als statisches Sprite eingeblendet. Die Manifestdatei hält Auflösung,
Tile-Statistik, Sprite-Auflösung und bekannte Grenzen fest.

Für die erkannte Lightmap-Ebene kann zusätzlich `--lightmap` verwendet werden:

```text
PYTHONDONTWRITEBYTECODE=1 python3 03_rendering/render_map.py \
  "/Users/aleksl/Library/CloudStorage/Dropbox/CODING PRODUCTION/ChatGPT Codex Experiments/Darkest Journey" \
  --map Map0041.lmu \
  --scale 2 \
  --lightmap \
  --out /private/tmp/darkest-journey-map0041-lightmap.png
```

Der Schalter berücksichtigt `ShowPicture`-Befehle, deren Bildname `lightmap`
enthält. Die Position wird als Mittelpunkt in der 320×240-RPG-Maker-
Koordinatenfläche interpretiert, der Zoom per Nearest-Neighbor umgesetzt und
die im Command gesetzte Transparenz angewendet. Ob ein Bild im Spiel als
transparent geladen wird, folgt dabei ebenfalls dem Command-Feld für die
transparente Farbe. Bei der aktuellen Lightmap von `Map0041` bedeutet das
eine 320×240-Ebene bei `(160,120)` mit 80 % Transparenz.

Die Zuordnung der Picture-Parameter und die Mittelpunkt-Positionierung sind an
der öffentlichen EasyRPG-Referenz ausgerichtet:

- [EasyRPG `game_interpreter.cpp`](https://raw.githubusercontent.com/EasyRPG/Player/master/src/game_interpreter.cpp)
- [EasyRPG `sprite_picture.cpp`](https://raw.githubusercontent.com/EasyRPG/Player/master/src/sprite_picture.cpp)

## Bewusste Grenzen des ersten Prototyps

Die Vorschau ist eine Diagnoseansicht und kein Ersatz für die Laufzeit. Noch
nicht ausgewertet werden:

- Eventseitenbedingungen und der tatsächliche aktive Seitenzustand
- Laufzeit-Tile-Substitutionsbefehle
- Passierbarkeitsbasierte Ebenen-/Z-Reihenfolge
- animierte Autotile-Frames; verwendet wird deterministisch Frame 0
- übrige Pictures außerhalb von `--lightmap`, Panoramen, Bildschirm-Tönungen
  und der übrige Laufzeitzustand

Mit `--lightmap` werden weiterhin keine Eventseitenbedingungen, `MovePicture`-
Folgezustände oder Picture-Töne/Effekte simuliert. Der Schalter ist daher eine
reproduzierbare statische Annäherung und keine vollständige Laufzeitaufnahme.

Diese Grenzen stehen ebenfalls im JSON-Manifest, damit spätere Renderer- oder
Kompatibilitätsprüfungen die Vorschau nicht versehentlich als pixelgenaue
Laufzeitsimulation interpretieren.
