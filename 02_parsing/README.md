# 02 – Parsing

Ziel ist ein verlässlicher Zugriff auf `RPG_RT.ldb`, `RPG_RT.lmt`, `Map*.lmu` und später gegebenenfalls `LSD`-Spielstände.

Der bevorzugte Unterbau ist `liblcf` beziehungsweise dessen Werkzeuge `lcf2xml` und `lcfstrings`. Ein eigener Layer soll darauf aufsetzen, die Daten in ein verständliches Modell überführen und projektbezogene Abhängigkeiten auswerten.
