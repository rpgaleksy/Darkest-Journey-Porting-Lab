# 05 – Runtime

Die Picture- und Kontrollflussanalyse hat gezeigt, dass zwischen Parser und
Renderer ein kleiner Runtime-Layer benötigt wird. Er soll ausgewählte
Eventpfade deterministisch ausführen und später als Grundlage einer
interaktiven macOS-Laufzeit dienen.

Die festgelegte Architektur, ihr erster Implementierungsslice und die Grenzen
gegenüber einer vollständigen Engine stehen in:

- [Event-Trace-Laufzeit für Pictures](event-trace-design.md)
- [Kooperativer Scheduler für parallele Events](parallel-scheduler-design.md)

## Implementierter erster Slice

`event_trace.py` führt ausgewählte Befehlslisten mit explizitem Zustand aus.
Unterstützt sind derzeit Switches, Variablen, indirekte Variablen,
Charakterwerte, Branches, Labels, Sprünge, Schleifen, Common-Event-Aufrufe,
klassische Picture-Befehle, Waits und lineare Picture-Übergänge.

`run_trace.py` stellt denselben Kern als read-only Kommandozeilenwerkzeug zur
Verfügung. Es gibt ein JSON-Diagnoseergebnis mit ausgeführtem Pfad, Haltegrund,
Frames, Switches, Variablen, Picture-Slots und protokollierten Aktionen aus.

`event_scheduler.py` ergänzt diesen Kern um fortsetzbare Sessions für mehrere
parallele Common Events und Map-Events. `run_scheduler.py` führt einen
begrenzten Frame-Ausschnitt gegen eine Map aus und schreibt dieselbe Art
JSON-Diagnose mit Task-Lebenszyklen, gemeinsamem Zustand und Timeline.

Der Renderer nutzt diesen Kern über `03_rendering/runtime_preview.py`. Eine
Profil- oder Trace-Datei kann damit konkrete Map-Events und Common Events als
begrenzte Zustandsfolge ausführen und den aktuellen Picture-Snapshot in eine
PNG-Vorschau übernehmen. Das Adaptermodul validiert die Eingaben, erzeugt
Character-Snapshots aus der Map und hält die Ergebnisse im Renderer-Manifest
fest; es dupliziert keine Interpreterlogik.

Beispiele gegen das externe Originalprojekt:

```text
python3 05_runtime/run_trace.py \
  "/Users/aleksl/Library/CloudStorage/Dropbox/CODING PRODUCTION/ChatGPT Codex Experiments/Darkest Journey" \
  --common-event 3 --facing 1 --screen-x 123 --screen-y 77 \
  --stop-after-wait --out /private/tmp/darkest-journey-trace.json

python3 05_runtime/run_trace.py \
  "/Users/aleksl/Library/CloudStorage/Dropbox/CODING PRODUCTION/ChatGPT Codex Experiments/Darkest Journey" \
  --common-event 14 --variable 113=1 --variable 122=19
```

Nachrichten, Tasteneingaben, Choices und Bewegungsrouten führen weiterhin zu
einem expliziten `awaiting_input`- oder `unsupported`-Ergebnis. Dadurch werden
fehlende Laufzeitdienste nicht als erfolgreich simuliert.

Beispiel für einen begrenzten Scheduler-Lauf gegen die Originaldaten:

```text
python3 05_runtime/run_scheduler.py \
  "/Users/aleksl/Library/CloudStorage/Dropbox/CODING PRODUCTION/ChatGPT Codex Experiments/Darkest Journey" \
  --map Map0064.lmu --frames 120 --switch 62=on \
  --facing 1 --screen-x 123 --screen-y 77 \
  --out /private/tmp/darkest-journey-scheduler.json
```

## Nächste Runtime-Grenzen

Die nächste größere Erweiterung sind externe Anbieter für Nachrichten,
Tasteneingaben und Bewegungsrouten sowie eine vollständige Auswertung der noch
nicht unterstützten Seitenbedingungen. Kartenwechsel und persistente
Speicherzustände bleiben bewusst außerhalb dieses Slices.
