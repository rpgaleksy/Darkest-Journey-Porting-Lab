# Tests

Kleine reproduzierbare Tests gehören hier hinein. Tests dürfen das Originalprojekt lesen, aber nicht verändern.

Die Parser-Tests verwenden ausschließlich synthetische LCF-Fixtures:

```text
python3 -m unittest discover -s tests -v
```

Der Testlauf prüft unter anderem komprimierte Integer, Chunk-Grenzen,
Windows-1252-Texte, Tile-Layer, Eventbedingungen und ein synthetisches
`ShowMessage`-Kommando.
