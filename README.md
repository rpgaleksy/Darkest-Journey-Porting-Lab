# Darkest Journey Porting Lab

Arbeitsbereich für die Analyse, Kompatibilitätsprüfung und mögliche Portierung von **Darkest Journey**.

Das Originalprojekt liegt außerhalb dieses Ordners und wird als schreibgeschützte Quelle behandelt:

`/Users/aleksl/Library/CloudStorage/Dropbox/CODING PRODUCTION/ChatGPT Codex Experiments/Darkest Journey`

## Grundregel

Kein Tool in diesem Arbeitsbereich schreibt in das Originalspiel. Analyseberichte und erzeugte Testdaten landen ausschließlich hier.

## Struktur

- `01_inventory/` – Dateiinventar, Projektmarker, Maps und Ressourcen
- `02_parsing/` – LCF/LDB/LMT/LMU-Parser und XML/JSON-Export
- `03_rendering/` – Map-Vorschauen und Ressourcen-Renderer
- `04_compatibility/` – EasyRPG-/Runtime-Kompatibilität und bekannte Abweichungen
- `05_runtime/` – spätere Laufzeit- oder Portierungsprototypen
- `06_reports/` – erzeugte Berichte, Tabellen und Diagramme
- `tests/` – kleine reproduzierbare Tests für Parser und Konvertierung
- `vendor/` – klar getrennte externe Werkzeuge oder Quellen, falls später benötigt

## Erste Meilensteine

`01_inventory/inventory.py` erzeugt ein read-only Inventar des Spiels. Es erfasst unter anderem:

- Dateien, Größen und Dateitypen
- Map-IDs und Lücken in der Map-Reihe
- RPG-Maker-Projektmarker aus `RPG_RT.ini`
- eingebettete Text-/Event-Signale aus LDB, LMT und LMU
- Hinweise auf das eigene Menü, Inventar, Notizen, Licht- und Kampfsystem

Beispiel:

```text
python3 01_inventory/inventory.py \
  "/Users/aleksl/Library/CloudStorage/Dropbox/CODING PRODUCTION/ChatGPT Codex Experiments/Darkest Journey" \
  --out-dir 06_reports
```

Die nächste Ausbaustufe ist ein strukturierter Parser auf Basis von `liblcf`, nicht das riskante direkte Umschreiben der Binärdateien.

Der erste Parser-Meilenstein ist nun vorhanden: `02_parsing/parse_project.py`
liest `RPG_RT.lmt` und eine ausgewählte `Map*.lmu` read-only und exportiert
Map-Metadaten, Layer, Events und Event-Kommandos als JSON. Die Nutzung und
die bewusst noch offenen Teilbereiche sind in
`02_parsing/README.md` beschrieben.
