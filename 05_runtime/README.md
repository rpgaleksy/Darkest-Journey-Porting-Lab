# 05 – Runtime

Die Picture- und Kontrollflussanalyse hat gezeigt, dass zwischen Parser und
Renderer ein kleiner Runtime-Layer benötigt wird. Er soll ausgewählte
Eventpfade deterministisch ausführen und später als Grundlage einer
interaktiven macOS-Laufzeit dienen.

Die festgelegte Architektur, ihr erster Implementierungsslice und die Grenzen
gegenüber einer vollständigen Engine stehen in:

- [Event-Trace-Laufzeit für Pictures](event-trace-design.md)

## Implementierter erster Slice

`event_trace.py` führt ausgewählte Befehlslisten mit explizitem Zustand aus.
Unterstützt sind derzeit Switches, Variablen, indirekte Variablen,
Charakterwerte, Branches, Labels, Sprünge, Schleifen, Common-Event-Aufrufe,
klassische Picture-Befehle, Waits und lineare Picture-Übergänge.

`run_trace.py` stellt denselben Kern als read-only Kommandozeilenwerkzeug zur
Verfügung. Es gibt ein JSON-Diagnoseergebnis mit ausgeführtem Pfad, Haltegrund,
Frames, Switches, Variablen, Picture-Slots und protokollierten Aktionen aus.

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
