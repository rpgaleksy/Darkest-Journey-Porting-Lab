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
Spiel verwendeten 8-Bit-PNGs, behandelt bei indizierten RPG-Maker-Grafiken den
Palettenindex 0 als transparent und rekonstruiert die bekannten Chipset-Blöcke
A–F auf 16×16-Tiles. Die Blockgrenzen und die Autotile-Quadranten sind an der
öffentlichen EasyRPG-Referenz ausgerichtet:

- [EasyRPG `map_data.h`](https://raw.githubusercontent.com/EasyRPG/Player/master/src/map_data.h)
- [EasyRPG `tilemap_layer.cpp`](https://raw.githubusercontent.com/EasyRPG/Player/master/src/tilemap_layer.cpp)

Zusätzlich wird pro Map-Event die erste Seite mit einem nichtleeren Charset-
Namen als statisches Sprite eingeblendet. Die Manifestdatei hält Auflösung,
Tile-Statistik, Sprite-Auflösung und bekannte Grenzen fest.

## Bewusste Grenzen des ersten Prototyps

Die Vorschau ist eine Diagnoseansicht und kein Ersatz für die Laufzeit. Noch
nicht ausgewertet werden:

- Eventseitenbedingungen und der tatsächliche aktive Seitenzustand
- Laufzeit-Tile-Substitutionsbefehle
- Passierbarkeitsbasierte Ebenen-/Z-Reihenfolge
- animierte Autotile-Frames; verwendet wird deterministisch Frame 0
- Pictures, Panoramen, Bildschirm-Tönungen und der übrige Laufzeitzustand

Diese Grenzen stehen ebenfalls im JSON-Manifest, damit spätere Renderer- oder
Kompatibilitätsprüfungen die Vorschau nicht versehentlich als pixelgenaue
Laufzeitsimulation interpretieren.
