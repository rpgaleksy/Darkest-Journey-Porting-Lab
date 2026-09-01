# Darkest Journey – Inventory Report

- Quelle: `/Users/aleksl/Library/CloudStorage/Dropbox/CODING PRODUCTION/ChatGPT Codex Experiments/Darkest Journey`
- Schreibmodus: read-only
- Dateien: **455**
- Größe: **43.58 MiB**
- Maps: **84** (IDs 1–87)
- Map-Lücken: 0039, 0040, 0081

## Dateitypen

| Endung | Anzahl |
|---|---:|
| `.png` | 216 |
| `.wav` | 117 |
| `.lmu` | 84 |
| `.mp3` | 15 |
| `.html` | 10 |
| `.mid` | 3 |
| `.dll` | 2 |
| `.fon` | 2 |
| `.bak` | 1 |
| `.exe` | 1 |
| `.ini` | 1 |
| `.ldb` | 1 |
| `.lmt` | 1 |
| `.txt` | 1 |

## RPG-Maker-Marker

- `[$RPG_RT]`
  - `GameTitle=DarkestJourney`
  - `MapEditMode=2`
  - `MapEditZoom=0`
  - `FullPackageFlag=1`

## Erkannte Projektsignale

- **custom_menu_modules:** `FirstStart`, `Menue_Beenden`, `Menue_ItemBesch`, `Menue_NotizenBesch`, `Menue_Save`, `Menue_Start`, `Menue_Steuerung`, `Menue_Textaufruf`, `Menue_aktivierbar`, `Menue_endAuswahl`, `Menue_initAuswahl`, `Menue_initItemanz`
- **menu_state_symbols:** `Menue_MapID`, `Menue_X`, `Menue_Y`
- **inventory_slots:** `Inventar[0]`, `Inventar[10]`, `Inventar[11]`, `Inventar[12]`, `Inventar[13]`, `Inventar[14]`, `Inventar[15]`, `Inventar[16]`, `Inventar[17]`, `Inventar[18]`, `Inventar[1]`, `Inventar[2]`, `Inventar[3]`, `Inventar[4]`, `Inventar[5]`, `Inventar[6]`, `Inventar[7]`, `Inventar[8]`, `Inventar[9]`, `Notizen[0]`, `Notizen[10]`, `Notizen[11]`, `Notizen[12]`, `Notizen[13]`, `Notizen[14]`, `Notizen[15]`, `Notizen[16]`, `Notizen[17]`, `Notizen[18]`, `Notizen[1]`, `Notizen[2]`, `Notizen[3]`, `Notizen[4]`, `Notizen[5]`, `Notizen[6]`, `Notizen[7]`, `Notizen[8]`, `Notizen[9]`
- **inventory_capacity_markers:** `Inventar[19]`, `Notizen[19]`
- **ending_markers:** `Ende 1`, `Ende 2`, `Ende 3`, `Ende 4`, `Ende 5`, `Ende Nummer`
- **light_cones:** `Sichtkegel_Hoch2`, `Sichtkegel_Links2`, `Sichtkegel_Rechts2`, `Sichtkegel_Runter2`
- **combat_markers:** `Gegner Hp`, `HP Waffe`, `Kampfsystem`, `Schaden`, `Schlag?`, `Waffe Nr.`, `schaden`
- **state_variables:** `MapID`, `Spielzeit`, `Tag`, `X_Position`, `Y_Position`, `Ziffer 1`, `Ziffer 2`, `Ziffer 3`, `Ziffer 4`, `Ziffer 5`, `Ziffer 6`, `tag`
- **dynamic_assets:** `Item_XXXX`, `Notiz_XXXX`

## Maps mit auffälliger Event-Dichte

| Map | Dateigröße | Event-Signale | Höchste Event-ID |
|---|---:|---:|---:|
| `Map0023.lmu` | 16689 B | 163 | 166 |
| `Map0006.lmu` | 17960 B | 112 | 123 |
| `Map0068.lmu` | 12910 B | 105 | 106 |
| `Map0070.lmu` | 20466 B | 70 | 73 |
| `Map0030.lmu` | 6007 B | 54 | 55 |
| `Map0027.lmu` | 6470 B | 53 | 54 |
| `Map0047.lmu` | 12805 B | 48 | 50 |
| `Map0025.lmu` | 5510 B | 47 | 48 |
| `Map0046.lmu` | 6479 B | 43 | 43 |
| `Map0029.lmu` | 8638 B | 41 | 48 |
| `Map0048.lmu` | 9920 B | 39 | 45 |
| `Map0015.lmu` | 12115 B | 38 | 41 |
| `Map0011.lmu` | 13041 B | 34 | 38 |
| `Map0054.lmu` | 4984 B | 33 | 35 |
| `Map0062.lmu` | 5954 B | 33 | 33 |

## Einordnung

Die Event-Signale sind heuristisch. Für verlässliche Befehls-, Switch- und Ressourcenabhängigkeiten ist der LCF-Parser in `02_parsing/` erforderlich.
