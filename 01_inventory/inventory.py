#!/usr/bin/env python3
"""Read-only inventory for an RPG Maker 2000/2003 project.

The scanner never writes to the source project. Reports are written only when
the caller supplies an explicit output directory.
"""

from __future__ import annotations

import argparse
import configparser
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


MAP_RE = re.compile(r"^Map(\d{4})\.lmu$", re.IGNORECASE)
EVENT_RE = re.compile(r"\bEV(\d{4})\b")


def decode_bytes(data: bytes) -> str:
    """Decode the encoding used by most German RPG Maker 2k projects."""

    return data.decode("cp1252", errors="replace")


def printable_runs(data: bytes, minimum: int = 4) -> list[str]:
    """Return approximate Windows-1252 strings embedded in LCF data.

    This is deliberately conservative and is used for signals only. It is not
    a replacement for a real LCF parser.
    """

    runs: list[str] = []
    current = bytearray()
    for value in data:
        is_printable = value in (9, 10, 13) or 32 <= value <= 126 or 160 <= value <= 255
        if is_printable:
            current.append(value)
        else:
            if len(current) >= minimum:
                text = decode_bytes(bytes(current)).replace("\x00", " ").strip()
                if text:
                    runs.append(text)
            current.clear()
    if len(current) >= minimum:
        text = decode_bytes(bytes(current)).replace("\x00", " ").strip()
        if text:
            runs.append(text)
    return runs


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def file_inventory(root: Path) -> tuple[list[dict], Counter, Counter]:
    records: list[dict] = []
    extensions: Counter = Counter()
    directories: Counter = Counter()

    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        stat = path.stat()
        suffix = path.suffix.lower() or "[no extension]"
        rel = relative(path, root)
        top_level = rel.split("/", 1)[0] if "/" in rel else "[root]"
        extensions[suffix] += 1
        directories[top_level] += 1
        records.append(
            {
                "path": rel,
                "size": stat.st_size,
                "extension": suffix,
                "top_level": top_level,
            }
        )
    return records, extensions, directories


def parse_ini(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read(path, encoding="cp1252")
    return {section: dict(parser[section]) for section in parser.sections()}


def map_inventory(root: Path) -> dict:
    maps: list[dict] = []
    for path in sorted(root.glob("Map*.lmu")):
        match = MAP_RE.match(path.name)
        if not match:
            continue
        data = path.read_bytes()
        event_ids = sorted({int(value) for value in EVENT_RE.findall(decode_bytes(data))})
        maps.append(
            {
                "id": int(match.group(1)),
                "file": path.name,
                "size": path.stat().st_size,
                "event_id_count_signal": len(event_ids),
                "highest_event_id_signal": max(event_ids) if event_ids else None,
            }
        )

    ids = [item["id"] for item in maps]
    gaps: list[int] = []
    if ids:
        gaps = [value for value in range(min(ids), max(ids) + 1) if value not in ids]
    return {
        "count": len(maps),
        "first_id": min(ids) if ids else None,
        "last_id": max(ids) if ids else None,
        "gaps": gaps,
        "maps": maps,
    }


def project_signals(root: Path) -> dict:
    data_files = [root / "RPG_RT.ldb", root / "RPG_RT.lmt", *sorted(root.glob("Map*.lmu"))]
    all_runs: list[str] = []
    per_file: dict[str, int] = {}
    for path in data_files:
        if not path.is_file():
            continue
        runs = printable_runs(path.read_bytes())
        all_runs.extend(runs)
        per_file[path.name] = len(runs)

    joined = "\n".join(all_runs)
    signal_patterns = {
        "custom_menu_modules": r"(?:FirstStart|Menue_(?:Start|Steuerung|Beenden|Textaufruf|Save|ItemBesch|NotizenBesch|endAuswahl|initAuswahl|initItemanz|aktivierbar))",
        "menu_state_symbols": r"Menue_(?:MapID|X|Y)",
        "inventory_slots": r"(?:Inventar|Notizen)\[(?:[0-9]|1[0-8])\]",
        "inventory_capacity_markers": r"(?:Inventar|Notizen)\[19\]",
        "ending_markers": r"(?:Ende [1-5]|Ende Nummer)",
        "light_cones": r"Sichtkegel_[A-Za-zÄÖÜäöü0-9]+",
        "combat_markers": r"(?:Kampfsystem|HP Waffe|Waffe Nr\.|Gegner Hp|Schaden|Schlag\?)",
        "state_variables": r"(?:MapID|X_Position|Y_Position|Spielzeit|TAG|Ziffer [1-6])",
        "dynamic_assets": r"(?:Item_XXXX|Notiz_XXXX)",
    }
    signals: dict[str, list[str]] = {}
    for name, pattern in signal_patterns.items():
        signals[name] = sorted(set(re.findall(pattern, joined, flags=re.IGNORECASE)))

    return {
        "printable_run_counts": per_file,
        "signals": signals,
    }


def readme_encoding(root: Path) -> dict:
    candidates = sorted(root.glob("README*")) + sorted(root.glob("READ-ME*"))
    if not candidates:
        return {}
    path = candidates[0]
    text = decode_bytes(path.read_bytes())
    return {
        "file": path.name,
        "characters": len(text),
        "contains_full_version": "Vollversion" in text,
        "contains_windows_font_instruction": "RMG2000" in text or "RM2000" in text,
    }


def build_inventory(root: Path) -> dict:
    records, extensions, directories = file_inventory(root)
    total_bytes = sum(record["size"] for record in records)
    return {
        "source": str(root),
        "read_only": True,
        "file_count": len(records),
        "total_bytes": total_bytes,
        "extensions": dict(sorted(extensions.items(), key=lambda item: (-item[1], item[0]))),
        "top_level_file_counts": dict(sorted(directories.items())),
        "rpg_maker_ini": parse_ini(root / "RPG_RT.ini"),
        "maps": map_inventory(root),
        "project_signals": project_signals(root),
        "readme": readme_encoding(root),
        "files": records,
    }


def markdown_report(report: dict) -> str:
    mb = report["total_bytes"] / (1024 * 1024)
    maps = report["maps"]
    lines = [
        "# Darkest Journey – Inventory Report",
        "",
        f"- Quelle: `{report['source']}`",
        "- Schreibmodus: read-only",
        f"- Dateien: **{report['file_count']}**",
        f"- Größe: **{mb:.2f} MiB**",
        f"- Maps: **{maps['count']}** (IDs {maps['first_id']}–{maps['last_id']})",
        f"- Map-Lücken: {', '.join(f'{value:04d}' for value in maps['gaps']) or 'keine'}",
        "",
        "## Dateitypen",
        "",
        "| Endung | Anzahl |",
        "|---|---:|",
    ]
    lines.extend(f"| `{extension}` | {count} |" for extension, count in report["extensions"].items())
    lines.extend(["", "## RPG-Maker-Marker", ""])
    ini = report["rpg_maker_ini"]
    if ini:
        for section, values in ini.items():
            lines.append(f"- `[${section}]`")
            lines.extend(f"  - `{key}={value}`" for key, value in values.items())
    else:
        lines.append("Keine `RPG_RT.ini` gefunden.")

    lines.extend(["", "## Erkannte Projektsignale", ""])
    signals = report["project_signals"]["signals"]
    for name, values in signals.items():
        rendered = ", ".join(f"`{value}`" for value in values) or "keine"
        lines.append(f"- **{name}:** {rendered}")

    lines.extend(["", "## Maps mit auffälliger Event-Dichte", "", "| Map | Dateigröße | Event-Signale | Höchste Event-ID |", "|---|---:|---:|---:|"])
    dense = sorted(
        (item for item in maps["maps"] if item["event_id_count_signal"]),
        key=lambda item: item["event_id_count_signal"],
        reverse=True,
    )[:15]
    for item in dense:
        lines.append(
            f"| `{item['file']}` | {item['size']} B | {item['event_id_count_signal']} | {item['highest_event_id_signal']} |"
        )
    if not dense:
        lines.append("| – | – | – | – |")

    lines.extend(["", "## Einordnung", "", "Die Event-Signale sind heuristisch. Für verlässliche Befehls-, Switch- und Ressourcenabhängigkeiten ist der LCF-Parser in `02_parsing/` erforderlich.", ""])
    return "\n".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Pfad zum RPG-Maker-Projekt")
    parser.add_argument("--out-dir", type=Path, help="Optionaler Ausgabeordner für inventory.json und inventory.md")
    args = parser.parse_args(argv)

    root = args.source.expanduser().resolve()
    if not root.is_dir():
        print(f"Quelle nicht gefunden: {root}", file=sys.stderr)
        return 2
    if not (root / "RPG_RT.ldb").is_file() and not (root / "RPG_RT.lmt").is_file():
        print("Warnung: RPG_RT.ldb/RPG_RT.lmt nicht gefunden; Inventar wird trotzdem erstellt.", file=sys.stderr)

    report = build_inventory(root)
    markdown = markdown_report(report)

    if args.out_dir:
        output = args.out_dir.expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        (output / "inventory.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output / "inventory.md").write_text(markdown, encoding="utf-8")
        print(f"Berichte geschrieben nach: {output}")
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
