# 05 – Runtime

Die Picture- und Kontrollflussanalyse hat gezeigt, dass zwischen Parser und
Renderer ein kleiner Runtime-Layer benötigt wird. Er soll ausgewählte
Eventpfade deterministisch ausführen und später als Grundlage einer
interaktiven macOS-Laufzeit dienen.

Die festgelegte Architektur, ihr erster Implementierungsslice und die Grenzen
gegenüber einer vollständigen Engine stehen in:

- [Event-Trace-Laufzeit für Pictures](event-trace-design.md)
