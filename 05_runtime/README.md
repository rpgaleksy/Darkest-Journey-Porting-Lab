# 05 – Runtime

Die Picture- und Kontrollflussanalyse hat gezeigt, dass zwischen Parser und
Renderer ein kleiner Runtime-Layer benötigt wird. Er soll ausgewählte
Eventpfade deterministisch ausführen und später als Grundlage einer
interaktiven macOS-Laufzeit dienen.

Die festgelegte Architektur, ihr erster Implementierungsslice und die Grenzen
gegenüber einer vollständigen Engine stehen in:

- [Event-Trace-Laufzeit für Pictures](event-trace-design.md)
- [Kooperativer Scheduler für parallele Events](parallel-scheduler-design.md)
- [Interaktiver macOS-Diagnosehost](interactive-host-design.md)

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

`runtime_providers.py` definiert außerdem explizite Anbieter-Verträge für
Nachrichten, Tasteneingaben und Bewegungsbefehle. `ProviderDecision` beschreibt
dabei sowohl einen erfolgreichen Dienstaufruf mit optionalem Wait als auch
sichtbare Haltepunkte oder Fehler. `ScriptedRuntimeProviders` ist ein kleiner
deterministischer Anbieter für Replay-Profile und Tests; ohne konfigurierten
Anbieter bleiben diese Befehle absichtlich blockiert.

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

Choices und unbekannte Bewegungssemantik führen weiterhin zu einem expliziten
`awaiting_input`- oder `unsupported`-Ergebnis, solange kein passender Anbieter
konfiguriert ist. Provider-Ergebnisse werden nur dann in Variablen,
Charakter-Snapshots oder Aktionen übernommen, wenn sie diese Änderung
ausdrücklich liefern.

Beispiel für einen begrenzten Scheduler-Lauf gegen die Originaldaten:

```text
python3 05_runtime/run_scheduler.py \
  "/Users/aleksl/Library/CloudStorage/Dropbox/CODING PRODUCTION/ChatGPT Codex Experiments/Darkest Journey" \
  --map Map0064.lmu --frames 120 --switch 62=on \
  --facing 1 --screen-x 123 --screen-y 77 \
  --out /private/tmp/darkest-journey-scheduler.json
```

## Nächste Runtime-Grenzen

Der nächste Implementierungsslice ist im Host-Entwurf festgelegt: zunächst
werden Provider-Requests für Nachrichten und wartende Tasteneingaben über
Frames hinweg fortsetzbar. Danach folgt ein dünner Tk-Diagnosehost, der einen
Originaldialog auf einer gecachten Map-Vorschau ausführt. Bewegungsrouten,
Kollision, Kartenwechsel und persistent gespeicherte Spielzustände bleiben
getrennte spätere Slices.
