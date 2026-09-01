# Tests

Kleine reproduzierbare Tests gehören hier hinein. Tests dürfen das Originalprojekt lesen, aber nicht verändern.

Die Parser-Tests verwenden ausschließlich synthetische LCF-Fixtures:

```text
python3 -m unittest discover -s tests -v
```

Der Testlauf prüft unter anderem komprimierte Integer, Chunk-Grenzen,
Windows-1252-Texte, little-endian-Festfelder, Tile-Layer, Eventbedingungen,
ein synthetisches `ShowMessage`-Kommando sowie eine LDB ohne Root-
Terminator mit Actors, Items, Terms, Systemdaten und Common Event. Die
Ressourcen-Fixture prüft außerdem case-insensitive Dateinamen, RTP-Fallback,
bekannte `ShowPicture`-Referenzen und die Auflösung eines `.link.wav`-Ziels.

`test_map_renderer.py` ergänzt synthetische Chipset-, Charset- und Map-Fixtures.
Damit werden die Standardbibliotheks-PNG-Roundtrips, die Transparenz über
Palettenindex 0, die A-/B-Autotile-Komposition, direkte E/F-Tiles, C-/D-Tiles
sowie das statische Event-Sprite und sein JSON-Manifest reproduzierbar geprüft.
Außerdem wird ein synthetischer `ShowPicture`-Befehl für die optionale
Lightmap-Ebene mit Command-gesteuerter Palette-0-Transparenz und Opacity geprüft.
Es werden keine Originalressourcen benötigt.
