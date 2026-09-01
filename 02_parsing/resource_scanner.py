"""Read-only resource/reference analysis for an RPG Maker project.

The scanner combines the semantic LDB/LMT/LMU parser with a conservative
resource resolver.  References are collected only from fields and event
commands whose resource role is known; arbitrary printable strings are not
presented as resource references.  Project files take precedence over
optional RTP roots, matching the usual override behavior of RPG Maker
projects.
"""

from __future__ import annotations

import hashlib
import re
import struct
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Sequence

from database_parser import parse_ldb
from project_parser import DEFAULT_ENCODING, parse_lmt, parse_lmu


MAP_FILE_RE = re.compile(r"^Map(\d{4})\.lmu$", re.IGNORECASE)

IMAGE_EXTENSIONS = (".png",)
AUDIO_EXTENSIONS = (".wav", ".mid", ".midi", ".mp3")
SOUND_EXTENSIONS = (".wav", ".mid", ".midi")

# Directory names are matched case-insensitively.  A None extension tuple
# means that every file in that directory is a potential movie resource.
RESOURCE_DIRECTORY_RULES = {
    "backdrop": ("backdrop", IMAGE_EXTENSIONS),
    "battle": ("battle", IMAGE_EXTENSIONS),
    "battle2": ("battle", IMAGE_EXTENSIONS),
    "charset": ("charset", IMAGE_EXTENSIONS),
    "chipset": ("chipset", IMAGE_EXTENSIONS),
    "faceset": ("faceset", IMAGE_EXTENSIONS),
    "gameover": ("gameover", IMAGE_EXTENSIONS),
    "monster": ("monster", IMAGE_EXTENSIONS),
    "music": ("music", AUDIO_EXTENSIONS),
    "mp3": ("music", (".mp3",)),
    "movie": ("movie", None),
    "panorama": ("panorama", IMAGE_EXTENSIONS),
    "picture": ("picture", IMAGE_EXTENSIONS),
    "sound": ("sound", SOUND_EXTENSIONS),
    "system": ("system", IMAGE_EXTENSIONS),
    "title": ("title", IMAGE_EXTENSIONS),
}

COMMAND_RESOURCE_KINDS = {
    10130: "faceset",  # ChangeFaceGraphic
    10630: "charset",  # ChangeSpriteAssociation
    10640: "faceset",  # ChangeActorFace
    10650: "charset",  # ChangeVehicleGraphic
    10660: "music",  # ChangeSystemBGM
    10670: "sound",  # ChangeSystemSFX
    10680: "system",  # ChangeSystemGraphics
    11110: "picture",  # ShowPicture
    11510: "music",  # PlayBGM
    11550: "sound",  # PlaySound
    11560: "movie",  # PlayMovie
    11710: "chipset",  # ChangeMapTileset
    11720: "panorama",  # ChangePBG
    13210: "backdrop",  # ChangeBattleBG
}

SYSTEM_RESOURCE_FIELDS = {
    "boat_name": "charset",
    "ship_name": "charset",
    "airship_name": "charset",
    "title_name": "title",
    "gameover_name": "gameover",
    "system_name": "system",
    "system2_name": "system",
    "frame_name": "system",
    "battletest_background": "backdrop",
}

SYSTEM_MUSIC_FIELDS = (
    "title_music",
    "battle_music",
    "battle_end_music",
    "inn_music",
    "boat_music",
    "ship_music",
    "airship_music",
    "gameover_music",
)

SYSTEM_SOUND_FIELDS = (
    "cursor_se",
    "decision_se",
    "cancel_se",
    "buzzer_se",
    "battle_se",
    "escape_se",
    "enemy_attack_se",
    "enemy_damaged_se",
    "actor_damaged_se",
    "dodge_se",
    "enemy_death_se",
    "item_se",
)

DISABLED_RESOURCE_NAMES = {"", "off", "(off)", "(none)"}


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _resource_kind(path: Path, root: Path) -> Optional[str]:
    relative = path.relative_to(root)
    if not relative.parts:
        return None
    rule = RESOURCE_DIRECTORY_RULES.get(relative.parts[0].casefold())
    if rule is None:
        return None
    kind, extensions = rule
    if extensions is not None and path.suffix.casefold() not in extensions:
        return None
    return kind


def _link_lines(data: bytes) -> List[str]:
    try:
        return data.decode("cp1252").splitlines()
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace").splitlines()


def _link_info(path: Path, root: Path, data: bytes) -> Optional[dict]:
    lines = [line.strip() for line in _link_lines(data)]
    if not lines:
        return None
    target = lines[0]
    if not target or (not target.startswith(".") and "\\" not in target):
        return None

    normalized_target = target.replace("\\", "/")
    target_path = (path.parent / Path(normalized_target)).resolve()
    root_path = root.resolve()
    target_relative = None
    target_exists = False
    try:
        target_relative = target_path.relative_to(root_path).as_posix()
        target_exists = target_path.is_file()
    except ValueError:
        pass

    return {
        "target": target,
        "target_normalized": normalized_target,
        "target_path": target_relative,
        "target_exists": target_exists,
        "control_lines": lines[1:],
    }


def _resource_format(kind: str, path: Path, root: Path, data: bytes) -> str:
    if kind == "music" and path.suffix.casefold() == ".wav":
        if _link_info(path, root, data):
            return "rpg-maker-link"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "wav"
    if data.startswith(b"MThd"):
        return "midi"
    if data.startswith(b"ID3") or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "mp3"
    return path.suffix.casefold().lstrip(".") or "unknown"


def _file_descriptor(path: Path, root: Path, root_label: str, kind: str) -> dict:
    data = path.read_bytes()
    descriptor = {
        "root": root_label,
        "path": path.relative_to(root).as_posix(),
        "kind": kind,
        "extension": path.suffix.casefold(),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "format": _resource_format(kind, path, root, data),
    }
    if descriptor["format"] == "png" and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        descriptor["pixel_dimensions"] = {
            "width": width,
            "height": height,
        }
    if descriptor["format"] == "rpg-maker-link":
        link = _link_info(path, root, data)
        if link is not None:
            descriptor["link"] = link
    return descriptor


class _ResourceIndex:
    def __init__(self, root: Path, label: str) -> None:
        self.root = root
        self.label = label
        self.files: List[dict] = []
        self.by_name: dict[tuple[str, str], List[dict]] = {}

        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            kind = _resource_kind(path, root)
            if kind is None:
                continue
            descriptor = _file_descriptor(path, root, label, kind)
            self.files.append(descriptor)
            key = (kind, _normalized(path.name))
            self.by_name.setdefault(key, []).append(descriptor)

    def metadata(self) -> dict:
        by_kind = Counter(item["kind"] for item in self.files)
        by_format = Counter(item["format"] for item in self.files)
        return {
            "name": self.label,
            "path": str(self.root),
            "resource_file_count": len(self.files),
            "resource_files_by_kind": dict(sorted(by_kind.items())),
            "resource_files_by_format": dict(sorted(by_format.items())),
        }


class _ReferenceCollector:
    def __init__(self) -> None:
        self.references: List[dict] = []

    def add(self, kind: str, value: object, source: Mapping[str, object]) -> bool:
        if not isinstance(value, str):
            return False
        name = value.strip()
        if _normalized(name) in DISABLED_RESOURCE_NAMES:
            return False
        self.references.append(
            {
                "kind": kind,
                "requested_name": name,
                "source": dict(source),
            }
        )
        return True


def _candidate_names(requested_name: str, kind: str) -> List[str]:
    clean = requested_name.replace("\\", "/").strip()
    basename = clean.rsplit("/", 1)[-1]
    if kind == "movie":
        return [basename]

    if kind == "music":
        extensions = AUDIO_EXTENSIONS
    elif kind == "sound":
        extensions = SOUND_EXTENSIONS
    else:
        extensions = IMAGE_EXTENSIONS

    if Path(basename).suffix.casefold() in extensions:
        return [basename]
    return [basename + extension for extension in extensions]


def _file_reference(descriptor: dict) -> dict:
    result = {
        "root": descriptor["root"],
        "path": descriptor["path"],
        "kind": descriptor["kind"],
    }
    if descriptor.get("format") == "rpg-maker-link":
        result["format"] = descriptor["format"]
        result["link"] = descriptor.get("link")
    return result


def _find_matches(
    index: _ResourceIndex,
    kind: str,
    candidates: Sequence[str],
) -> List[dict]:
    matches: List[dict] = []
    seen = set()
    for candidate in candidates:
        for descriptor in index.by_name.get((kind, _normalized(candidate)), []):
            key = (descriptor["root"], descriptor["path"])
            if key not in seen:
                seen.add(key)
                matches.append(descriptor)
    return matches


def _resolve(reference: dict, indexes: Sequence[_ResourceIndex]) -> dict:
    candidates = _candidate_names(reference["requested_name"], reference["kind"])
    for index_position, index in enumerate(indexes):
        matches = _find_matches(index, reference["kind"], candidates)
        if not matches:
            continue

        shadowed = []
        for other_index in indexes[index_position + 1:]:
            shadowed.extend(
                _file_reference(item)
                for item in _find_matches(other_index, reference["kind"], candidates)
            )
        result = {
            "status": "resolved" if len(matches) == 1 else "ambiguous",
            "candidate_names": candidates,
            "root": index.label,
            "matched_files": [_file_reference(item) for item in matches],
        }
        if shadowed:
            result["shadowed_matches"] = shadowed
        return result

    return {
        "status": "missing",
        "candidate_names": candidates,
        "matched_files": [],
    }


def _add_record_reference(
    collector: _ReferenceCollector,
    kind: str,
    record: Mapping[str, object],
    field: str,
    source: Mapping[str, object],
) -> None:
    value = record.get(field)
    if value is not None:
        collector.add(kind, value, {**source, "field": field})


def _collect_command_references(
    collector: _ReferenceCollector,
    commands: Iterable[Mapping[str, object]],
    source: Mapping[str, object],
) -> int:
    count = 0
    for command_index, command in enumerate(commands):
        kind = COMMAND_RESOURCE_KINDS.get(command.get("code"))
        if kind is None:
            continue
        if collector.add(
            kind,
            command.get("string"),
            {
                **source,
                "command_index": command_index,
                "command_code": command.get("code"),
                "command_name": command.get("code_name"),
            },
        ):
            count += 1
    return count


def _collect_database_references(
    collector: _ReferenceCollector,
    database_report: dict,
) -> int:
    database = database_report["database"]
    before = len(collector.references)

    for section_name, field, kind in (
        ("actors", "character_name", "charset"),
        ("actors", "face_name", "faceset"),
        ("animations", "animation_name", "battle"),
        ("chipsets", "chipset_name", "chipset"),
        ("enemies", "battler_name", "monster"),
    ):
        for record in database.get(section_name, {}).get("records", []):
            _add_record_reference(
                collector,
                kind,
                record,
                field,
                {
                    "file": "RPG_RT.ldb",
                    "section": section_name,
                    "record_id": record.get("id"),
                },
            )

    for record in database.get("skills", {}).get("records", []):
        sound = record.get("sound_effect")
        if isinstance(sound, dict):
            collector.add(
                "sound",
                sound.get("name"),
                {
                    "file": "RPG_RT.ldb",
                    "section": "skills",
                    "record_id": record.get("id"),
                    "field": "sound_effect.name",
                },
            )

    for record in database.get("terrains", {}).get("records", []):
        source = {
            "file": "RPG_RT.ldb",
            "section": "terrains",
            "record_id": record.get("id"),
        }
        for field in ("background_name", "background_a_name", "background_b_name"):
            _add_record_reference(collector, "backdrop", record, field, source)

    system = database.get("system", {})
    for field, kind in SYSTEM_RESOURCE_FIELDS.items():
        if field in system:
            collector.add(
                kind,
                system.get(field),
                {"file": "RPG_RT.ldb", "section": "system", "field": field},
            )
    for field in SYSTEM_MUSIC_FIELDS:
        value = system.get(field)
        collector.add(
            "music",
            value.get("name") if isinstance(value, dict) else None,
            {"file": "RPG_RT.ldb", "section": "system", "field": f"{field}.name"},
        )
    for field in SYSTEM_SOUND_FIELDS:
        value = system.get(field)
        collector.add(
            "sound",
            value.get("name") if isinstance(value, dict) else None,
            {"file": "RPG_RT.ldb", "section": "system", "field": f"{field}.name"},
        )

    for record in database.get("commonevents", {}).get("records", []):
        commands = record.get("event_commands", {}).get("commands", [])
        _collect_command_references(
            collector,
            commands,
            {
                "file": "RPG_RT.ldb",
                "section": "commonevents",
                "record_id": record.get("id"),
                "record_name": record.get("name"),
            },
        )
    return len(collector.references) - before


def _collect_lmt_references(
    collector: _ReferenceCollector,
    lmt_report: dict,
) -> int:
    before = len(collector.references)
    for map_info in lmt_report.get("maps", []):
        source = {
            "file": "RPG_RT.lmt",
            "section": "map_info",
            "map_id": map_info.get("id"),
            "map_name": map_info.get("name"),
        }
        music = map_info.get("music")
        collector.add(
            "music",
            music.get("name") if isinstance(music, dict) else None,
            {**source, "field": "music.name"},
        )
        collector.add(
            "backdrop",
            map_info.get("background_name"),
            {**source, "field": "background_name"},
        )
    return len(collector.references) - before


def _collect_lmu_references(
    collector: _ReferenceCollector,
    map_filename: str,
    map_report: dict,
    chipset_names: Mapping[int, str],
) -> tuple[int, int]:
    map_data = map_report["map"]
    before = len(collector.references)
    command_references = 0
    chipset_id = map_data.get("chipset_id")
    chipset_name = (
        chipset_names.get(chipset_id)
        if isinstance(chipset_id, int)
        else None
    )
    collector.add(
        "chipset",
        chipset_name,
        {
            "file": map_filename,
            "section": "map",
            "field": "chipset_id",
            "record_id": chipset_id,
        },
    )
    collector.add(
        "panorama",
        map_data.get("parallax_name"),
        {"file": map_filename, "section": "map", "field": "parallax_name"},
    )
    events = map_data.get("events", {}).get("events", [])
    for event in events:
        event_source = {
            "file": map_filename,
            "section": "event",
            "event_id": event.get("id"),
            "event_name": event.get("name"),
        }
        for page_index, page in enumerate(event.get("pages", {}).get("pages", [])):
            page_source = {**event_source, "page_index": page_index}
            collector.add(
                "charset",
                page.get("character_name"),
                {**page_source, "field": "character_name"},
            )
            command_references += _collect_command_references(
                collector,
                page.get("event_commands", {}).get("commands", []),
                page_source,
            )
    return len(collector.references) - before, command_references


def _diagnostic_count(value: object, key: str) -> int:
    if isinstance(value, dict):
        own = len(value.get(key, [])) if isinstance(value.get(key), list) else 0
        return own + sum(_diagnostic_count(item, key) for item in value.values())
    if isinstance(value, list):
        return sum(_diagnostic_count(item, key) for item in value)
    return 0


def _asset_summaries(references: List[dict]) -> List[dict]:
    assets: dict[tuple[str, str], dict] = {}
    for reference in references:
        resolution = reference["resolution"]
        key = (reference["kind"], _normalized(reference["requested_name"]))
        asset = assets.setdefault(
            key,
            {
                "kind": reference["kind"],
                "requested_name": reference["requested_name"],
                "status": resolution["status"],
                "occurrence_count": 0,
                "matched_files": resolution.get("matched_files", []),
            },
        )
        asset["occurrence_count"] += 1
    return sorted(
        assets.values(),
        key=lambda item: (item["kind"], _normalized(item["requested_name"])),
    )


def markdown_report(report: dict) -> str:
    summary = report["summary"]
    lines = [
        "# Darkest Journey – Ressourcen- und Referenzanalyse",
        "",
        f"- Quelle: `{report['project']['source']}`",
        "- Schreibmodus: read-only",
        f"- Erkannte Ressourcendateien: **{summary['resource_file_count']}**",
        f"- Referenzvorkommen aus bekannten LCF-Feldern/Kommandos: **{summary['reference_occurrences']}**",
        f"- Geparste Maps: **{report['coverage']['map_files_parsed']}** von **{report['coverage']['map_files_discovered']}**",
        "",
        "## Auflösung",
        "",
        "| Ressourcentyp | Vorkommen | Einmalige Namen | Aufgelöst | Fehlend | Mehrdeutig |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for kind, values in report["summary"]["by_kind"].items():
        lines.append(
            f"| `{kind}` | {values['occurrences']} | {values['unique_references']} | "
            f"{values['resolved_occurrences']} | {values['missing_occurrences']} | "
            f"{values['ambiguous_occurrences']} |"
        )

    lines.extend(["", "## Parserabdeckung", ""])
    coverage = report["coverage"]
    lines.extend(
        [
            f"- Map-Events: **{coverage['map_events']}**",
            f"- Map-Event-Kommandos: **{coverage['map_event_commands']}**",
            f"- Common Events: **{coverage['common_events']}**",
            f"- Common-Event-Kommandos: **{coverage['common_event_commands']}**",
            f"- Map-Parsefehler: **{len(coverage['map_parse_errors'])}**",
        ]
    )

    missing = [item for item in report["assets"] if item["status"] == "missing"]
    lines.extend(["", "## Fehlende Referenzen", ""])
    if missing:
        lines.extend(
            f"- `{item['kind']}` – `{item['requested_name']}` "
            f"(Vorkommen: {item['occurrence_count']})"
            for item in missing[:50]
        )
        if len(missing) > 50:
            lines.append(f"- … und {len(missing) - 50} weitere")
    else:
        lines.append("Keine fehlenden Referenzen in den bekannten Feldern.")

    link_files = [
        item
        for item in report["files"]
        if item.get("format") == "rpg-maker-link"
    ]
    lines.extend(["", "## RPG-Maker-Linkdateien", ""])
    if link_files:
        for item in link_files:
            link = item.get("link", {})
            state = "vorhanden" if link.get("target_exists") else "fehlt"
            lines.append(
                f"- `{item['path']}` → `{link.get('target_normalized')}` ({state})"
            )
    else:
        lines.append("Keine Linkdateien erkannt.")

    lines.extend(
        [
            "",
            "## Einordnung",
            "",
            "Nicht referenzierte Dateien bedeuten hier nicht automatisch, dass sie "
            "im Spiel ungenutzt sind: Der Bericht bewertet nur die aktuell "
            "semantisch bekannten LDB/LMT/LMU-Felder und Event-Kommandos.",
            "",
        ]
    )
    return "\n".join(lines)


def scan_resources(
    project_dir: Path | str,
    *,
    rtp_dirs: Iterable[Path | str] = (),
    encoding: str = DEFAULT_ENCODING,
) -> dict:
    """Parse a project and resolve known resource references read-only."""

    project_path = Path(project_dir).expanduser().resolve()
    if not project_path.is_dir():
        raise FileNotFoundError(f"project directory does not exist: {project_path}")

    if isinstance(rtp_dirs, (str, Path)):
        rtp_dirs = (rtp_dirs,)
    rtp_paths = [Path(path).expanduser().resolve() for path in rtp_dirs]
    for rtp_path in rtp_paths:
        if not rtp_path.is_dir():
            raise FileNotFoundError(f"RTP directory does not exist: {rtp_path}")

    indexes = [_ResourceIndex(project_path, "project")]
    indexes.extend(
        _ResourceIndex(path, f"rtp_{index}")
        for index, path in enumerate(rtp_paths, start=1)
    )

    ldb_report = parse_ldb(project_path / "RPG_RT.ldb", encoding=encoding)
    lmt_report = parse_lmt(project_path / "RPG_RT.lmt", encoding=encoding)
    collector = _ReferenceCollector()
    database_reference_count = _collect_database_references(collector, ldb_report)
    lmt_reference_count = _collect_lmt_references(collector, lmt_report)
    chipset_names = {
        record["id"]: record["chipset_name"]
        for record in ldb_report["database"].get("chipsets", {}).get("records", [])
        if isinstance(record.get("id"), int)
        and isinstance(record.get("chipset_name"), str)
    }

    map_paths = sorted(
        path
        for path in project_path.iterdir()
        if path.is_file() and MAP_FILE_RE.match(path.name)
    )
    map_parse_errors = []
    map_events = 0
    map_event_commands = 0
    map_reference_count = 0
    map_command_reference_count = 0
    parsed_maps = 0
    for map_path in map_paths:
        try:
            map_report = parse_lmu(map_path, encoding=encoding)
        except (OSError, ValueError) as error:
            map_parse_errors.append({"file": map_path.name, "message": str(error)})
            continue
        parsed_maps += 1
        map_data = map_report["map"]
        events = map_data.get("events", {}).get("events", [])
        map_events += len(events)
        for event in events:
            for page in event.get("pages", {}).get("pages", []):
                map_event_commands += page.get("event_commands", {}).get(
                    "command_count", 0
                )
        references, command_references = _collect_lmu_references(
            collector,
            map_path.name,
            map_report,
            chipset_names,
        )
        map_reference_count += references
        map_command_reference_count += command_references

    common_events = ldb_report["database"].get("commonevents", {}).get("records", [])
    common_event_commands = sum(
        record.get("event_commands", {}).get("command_count", 0)
        for record in common_events
    )

    for reference in collector.references:
        reference["resolution"] = _resolve(reference, indexes)

    usage = Counter()
    descriptors_by_path = {
        (item["root"], item["path"]): item
        for index in indexes
        for item in index.files
    }
    for reference in collector.references:
        for match in reference["resolution"].get("matched_files", []):
            usage[(match["root"], match["path"])] += 1
            descriptor = descriptors_by_path.get((match["root"], match["path"]))
            link = descriptor.get("link") if descriptor is not None else None
            if link and link.get("target_exists") and link.get("target_path"):
                usage[(match["root"], link["target_path"])] += 1

    files = []
    for index in indexes:
        for descriptor in index.files:
            item = dict(descriptor)
            item["reference_count"] = usage[(item["root"], item["path"])]
            files.append(item)
    files.sort(key=lambda item: (item["root"], item["path"]))

    assets = _asset_summaries(collector.references)
    status_counts = Counter(
        reference["resolution"]["status"] for reference in collector.references
    )
    unique_by_kind = Counter(asset["kind"] for asset in assets)
    by_kind = {}
    for kind in sorted(unique_by_kind):
        kind_references = [
            item for item in collector.references if item["kind"] == kind
        ]
        kind_statuses = Counter(
            item["resolution"]["status"] for item in kind_references
        )
        by_kind[kind] = {
            "occurrences": len(kind_references),
            "unique_references": unique_by_kind[kind],
            "resolved_occurrences": kind_statuses["resolved"],
            "missing_occurrences": kind_statuses["missing"],
            "ambiguous_occurrences": kind_statuses["ambiguous"],
        }

    unreferenced = [
        {
            "root": item["root"],
            "path": item["path"],
            "kind": item["kind"],
            "size_bytes": item["size_bytes"],
        }
        for item in files
        if item["reference_count"] == 0
    ]

    report = {
        "schema_version": 1,
        "scanner": {
            "name": "darkest-journey-resource-scan",
            "version": "0.1.0",
            "read_only": True,
            "encoding": encoding,
        },
        "project": {
            "directory_name": project_path.name,
            "source": str(project_path),
        },
        "roots": [index.metadata() for index in indexes],
        "coverage": {
            "ldb_sections": ldb_report["database"].get("section_counts", {}),
            "lmt_map_records": lmt_report.get("map_count", 0),
            "map_files_discovered": len(map_paths),
            "map_files_parsed": parsed_maps,
            "map_parse_errors": map_parse_errors,
            "map_events": map_events,
            "map_event_commands": map_event_commands,
            "common_events": len(common_events),
            "common_event_commands": common_event_commands,
            "database_reference_occurrences": database_reference_count,
            "lmt_reference_occurrences": lmt_reference_count,
            "map_reference_occurrences": map_reference_count,
            "map_command_reference_occurrences": map_command_reference_count,
        },
        "diagnostics": {
            "ldb_field_decode_errors": _diagnostic_count(ldb_report, "field_decode_errors"),
            "ldb_warnings": _diagnostic_count(ldb_report, "warnings"),
            "lmt_field_decode_errors": _diagnostic_count(lmt_report, "field_decode_errors"),
            "lmt_warnings": _diagnostic_count(lmt_report, "warnings"),
        },
        "summary": {
            "resource_file_count": len(files),
            "reference_occurrences": len(collector.references),
            "unique_references": len(assets),
            "resolved_occurrences": status_counts["resolved"],
            "missing_occurrences": status_counts["missing"],
            "ambiguous_occurrences": status_counts["ambiguous"],
            "unreferenced_known_scope": len(unreferenced),
            "by_kind": by_kind,
        },
        "references": collector.references,
        "assets": assets,
        "files": files,
        "unreferenced_resources": unreferenced,
    }
    return report
