#!/usr/bin/env python3
"""Render a reproducible, read-only batch of RPG Maker map previews."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
PARSER_DIR = REPO_ROOT / "02_parsing"
if str(PARSER_DIR) not in sys.path:
    sys.path.insert(0, str(PARSER_DIR))

from lcf_reader import LcfParseError
from map_renderer import EventState, render_map, write_png
from project_parser import parse_lmt, parse_lmu
from runtime_preview import normalize_trace_specs


MAP_FILENAME_PATTERN = re.compile(r"Map\d{4}\.lmu", re.IGNORECASE)
DEFAULT_REPRESENTATIVE_COUNT = 7


@dataclass(frozen=True)
class PreviewProfile:
    """Named state and renderer options for one batch variant."""

    name: str
    switches: Mapping[int, bool] = field(default_factory=dict)
    variables: Mapping[int, int] = field(default_factory=dict)
    lightmap: bool = False
    pictures: bool = False
    traces: Tuple[Mapping[str, object], ...] = ()
    picture_snapshot: str = "target"
    maps: Optional[Tuple[str, ...]] = None

    def applies_to(self, map_filename: str) -> bool:
        return self.maps is None or map_filename in self.maps


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def _identifier(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} ID must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} ID must be a positive integer") from error
    if parsed < 1:
        raise ValueError(f"{label} ID must be a positive integer")
    return parsed


def _state_mapping(raw: object, label: str, *, boolean: bool) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"profile {label} must be a JSON object")

    result = {}
    for raw_id, raw_value in raw.items():
        identifier = _identifier(raw_id, label)
        if boolean:
            if not isinstance(raw_value, bool):
                raise ValueError(f"profile {label} values must be booleans")
            result[identifier] = raw_value
        else:
            if isinstance(raw_value, bool) or not isinstance(raw_value, int):
                raise ValueError(f"profile {label} values must be integers")
            result[identifier] = raw_value
    return dict(sorted(result.items()))


def _profile_from_mapping(raw: object, index: int) -> PreviewProfile:
    if not isinstance(raw, Mapping):
        raise ValueError(f"profile {index} must be a JSON object")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"profile {index} needs a non-empty name")
    lightmap = raw.get("lightmap", False)
    if not isinstance(lightmap, bool):
        raise ValueError(f"profile {name!r} lightmap must be boolean")
    pictures = raw.get("pictures", False)
    if not isinstance(pictures, bool):
        raise ValueError(f"profile {name!r} pictures must be boolean")
    if lightmap and pictures:
        raise ValueError(f"profile {name!r} cannot enable both lightmap and pictures")
    traces = normalize_trace_specs(raw.get("traces"))
    if traces and (lightmap or pictures):
        raise ValueError(
            f"profile {name!r} cannot combine traces with lightmap or pictures"
        )
    picture_snapshot = raw.get(
        "picture_snapshot",
        "current" if traces else "target",
    )
    if picture_snapshot not in {"target", "current"}:
        raise ValueError(
            f"profile {name!r} picture_snapshot must be 'target' or 'current'"
        )

    raw_maps = raw.get("maps")
    maps = None
    if raw_maps is not None:
        if not isinstance(raw_maps, list) or not all(
            isinstance(map_name, str) and map_name.strip() for map_name in raw_maps
        ):
            raise ValueError(f"profile {name!r} maps must be a list of filenames")
        maps = tuple(dict.fromkeys(raw_maps))

    return PreviewProfile(
        name=name.strip(),
        switches=_state_mapping(raw.get("switches"), "switches", boolean=True),
        variables=_state_mapping(raw.get("variables"), "variables", boolean=False),
        lightmap=lightmap,
        pictures=pictures,
        traces=traces,
        picture_snapshot=picture_snapshot,
        maps=maps,
    )


def _safe_name(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return result or "profile"


def load_profiles(path: Path | str) -> Tuple[PreviewProfile, ...]:
    """Load named preview profiles from a small JSON configuration file."""

    profile_path = Path(path).expanduser().resolve()
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    raw_profiles = payload.get("profiles") if isinstance(payload, Mapping) else payload
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise ValueError("profile file must contain a non-empty 'profiles' list")

    profiles = tuple(
        _profile_from_mapping(raw_profile, index)
        for index, raw_profile in enumerate(raw_profiles, start=1)
    )
    names = [profile.name for profile in profiles]
    if len(set(names)) != len(names):
        raise ValueError("profile names must be unique")
    slugs = [_safe_name(name) for name in names]
    if len(set(slugs)) != len(slugs):
        raise ValueError("profile names must produce unique output filenames")
    return profiles


def _map_events(map_data: Mapping[str, object]) -> list:
    events_data = map_data.get("events", {})
    if not isinstance(events_data, Mapping):
        return []
    events = events_data.get("events", [])
    return events if isinstance(events, list) else []


def _map_metrics(path: Path) -> dict:
    report = parse_lmu(path)
    map_data = report["map"]
    dimensions = map_data.get("dimensions", {})
    if not isinstance(dimensions, Mapping):
        dimensions = {}
    width = dimensions.get("width")
    height = dimensions.get("height")
    width = width if isinstance(width, int) and width > 0 else 0
    height = height if isinstance(height, int) and height > 0 else 0

    events = _map_events(map_data)
    pages_total = 0
    conditional_pages = 0
    show_picture_commands = 0
    lightmap_commands = 0
    for event in events:
        if not isinstance(event, Mapping):
            continue
        pages_data = event.get("pages", {})
        pages = pages_data.get("pages", []) if isinstance(pages_data, Mapping) else []
        if not isinstance(pages, list):
            continue
        pages_total += len(pages)
        for page in pages:
            if not isinstance(page, Mapping):
                continue
            condition = page.get("condition", {})
            if isinstance(condition, Mapping) and condition.get("flags", 0):
                conditional_pages += 1
            commands_data = page.get("event_commands", {})
            commands = (
                commands_data.get("commands", [])
                if isinstance(commands_data, Mapping)
                else []
            )
            if not isinstance(commands, list):
                continue
            for command in commands:
                if not isinstance(command, Mapping) or command.get("code") != 11110:
                    continue
                show_picture_commands += 1
                picture_name = command.get("string")
                if isinstance(picture_name, str) and "lightmap" in picture_name.casefold():
                    lightmap_commands += 1

    return {
        "map_filename": path.name,
        "width": width,
        "height": height,
        "area": width * height,
        "events": len(events),
        "pages": pages_total,
        "conditional_pages": conditional_pages,
        "show_picture_commands": show_picture_commands,
        "lightmap_commands": lightmap_commands,
    }


def collect_map_metrics(project_dir: Path | str) -> Tuple[List[dict], List[dict]]:
    """Parse map headers and event structures for deterministic selection."""

    project_path = Path(project_dir).expanduser().resolve()
    if not project_path.is_dir():
        raise FileNotFoundError(f"project directory does not exist: {project_path}")
    metrics = []
    errors = []
    for path in sorted(project_path.glob("Map*.lmu"), key=lambda item: item.name):
        if not MAP_FILENAME_PATTERN.fullmatch(path.name):
            continue
        try:
            metrics.append(_map_metrics(path))
        except (OSError, LcfParseError, ValueError) as error:
            errors.append({"map_filename": path.name, "message": str(error)})
    return metrics, errors


def _best_metric(metrics: Sequence[Mapping[str, object]], field_name: str) -> Optional[dict]:
    if not metrics:
        return None
    return dict(
        sorted(
            metrics,
            key=lambda item: (
                -int(item.get(field_name, 0) or 0),
                str(item.get("map_filename", "")),
            ),
        )[0]
    )


def select_representative_maps(
    metrics: Sequence[Mapping[str, object]],
    count: int = DEFAULT_REPRESENTATIVE_COUNT,
    *,
    start_map_filename: Optional[str] = None,
) -> Tuple[List[str], List[dict], Mapping[str, List[str]]]:
    """Select maps by stable coverage criteria rather than map-number order."""

    if count < 1:
        raise ValueError("representative map count must be at least 1")
    by_name = {
        str(item["map_filename"]): dict(item)
        for item in metrics
        if isinstance(item.get("map_filename"), str)
    }
    ordered_metrics = [by_name[name] for name in sorted(by_name)]
    chosen: List[str] = []
    reasons = {}
    criteria = []

    def consider(label: str, candidate: Optional[Mapping[str, object]]) -> None:
        if candidate is None:
            return
        map_filename = str(candidate["map_filename"])
        selected = map_filename not in chosen and len(chosen) < count
        reasons.setdefault(map_filename, []).append(label)
        if selected:
            chosen.append(map_filename)
        criteria.append(
            {
                "criterion": label,
                "map_filename": map_filename,
                "selected": selected,
            }
        )

    if start_map_filename is not None:
        consider("start_map", by_name.get(start_map_filename))
    consider("largest_area", _best_metric(ordered_metrics, "area"))
    consider("most_events", _best_metric(ordered_metrics, "events"))
    consider("most_conditional_pages", _best_metric(ordered_metrics, "conditional_pages"))
    consider("most_picture_commands", _best_metric(ordered_metrics, "show_picture_commands"))
    lightmap_metrics = [
        item for item in ordered_metrics if int(item.get("lightmap_commands", 0) or 0) > 0
    ]
    consider("lightmap_picture", _best_metric(lightmap_metrics, "lightmap_commands"))
    consider("tallest_map", _best_metric(ordered_metrics, "height"))

    for item in sorted(
        ordered_metrics,
        key=lambda candidate: (
            -int(candidate.get("area", 0) or 0),
            -int(candidate.get("events", 0) or 0),
            str(candidate["map_filename"]),
        ),
    ):
        if len(chosen) >= count:
            break
        map_filename = str(item["map_filename"])
        if map_filename in chosen:
            continue
        chosen.append(map_filename)
        reasons.setdefault(map_filename, []).append("coverage_fill")
        criteria.append(
            {
                "criterion": "coverage_fill",
                "map_filename": map_filename,
                "selected": True,
            }
        )

    return chosen, criteria, reasons


def _resolve_map_selection(
    metrics: Sequence[Mapping[str, object]],
    *,
    map_filenames: Optional[Sequence[str]],
    all_maps: bool,
    representative_count: int,
    start_map_filename: Optional[str],
) -> Tuple[List[str], dict]:
    available = {
        str(item["map_filename"]): dict(item)
        for item in metrics
        if isinstance(item.get("map_filename"), str)
    }
    if not available:
        raise ValueError("no parseable MapNNNN.lmu files found")
    if map_filenames and all_maps:
        raise ValueError("--map and --all-maps cannot be used together")

    if map_filenames:
        selected = list(dict.fromkeys(map_filenames))
        missing = [name for name in selected if name not in available]
        if missing:
            raise FileNotFoundError(
                "requested map does not exist or could not be parsed: "
                + ", ".join(missing)
            )
        return selected, {
            "mode": "explicit",
            "representative_count": None,
            "criteria": [],
            "maps": [available[name] for name in selected],
        }

    if all_maps:
        selected = sorted(available)
        return selected, {
            "mode": "all",
            "representative_count": None,
            "criteria": [],
            "maps": [available[name] for name in selected],
        }

    selected, criteria, reasons = select_representative_maps(
        list(available.values()),
        representative_count,
        start_map_filename=start_map_filename,
    )
    selected_metrics = []
    for name in selected:
        item = dict(available[name])
        item["selected_by"] = reasons.get(name, [])
        selected_metrics.append(item)
    return selected, {
        "mode": "representative",
        "representative_count": representative_count,
        "criteria": criteria,
        "maps": selected_metrics,
    }


def _project_start_map_filename(project_path: Path) -> Optional[str]:
    start = parse_lmt(project_path / "RPG_RT.lmt").get("start", {})
    if not isinstance(start, Mapping):
        return None
    map_id = start.get("party_map_id")
    if not isinstance(map_id, int) or map_id < 1:
        return None
    return f"Map{map_id:04d}.lmu"


def _profile_manifest(profile: PreviewProfile) -> dict:
    result = {
        "name": profile.name,
        "lightmap": profile.lightmap,
        "pictures": profile.pictures,
        "picture_snapshot": profile.picture_snapshot,
        "traces": [dict(trace) for trace in profile.traces],
        "switches": [
            {"id": identifier, "value": value}
            for identifier, value in sorted(profile.switches.items())
        ],
        "variables": [
            {"id": identifier, "value": value}
            for identifier, value in sorted(profile.variables.items())
        ],
    }
    if profile.maps is not None:
        result["maps"] = list(profile.maps)
    return result


def _within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _render_summary(manifest: Mapping[str, object]) -> dict:
    tiles = manifest.get("tiles", {})
    events = manifest.get("events", {})
    pictures = manifest.get("pictures", {})
    tiles = tiles if isinstance(tiles, Mapping) else {}
    events = events if isinstance(events, Mapping) else {}
    pictures = pictures if isinstance(pictures, Mapping) else {}
    return {
        "output": manifest.get("output", {}),
        "tiles": {
            "rendered": tiles.get("rendered_tiles", 0),
            "unsupported": tiles.get("unsupported_tiles", 0),
        },
        "events": {
            "total": events.get("events_total", 0),
            "active_pages": events.get("active_pages", 0),
            "sprites_drawn": events.get("sprites_drawn", 0),
            "ambiguous": len(events.get("ambiguous_events", [])),
        },
        "pictures": {
            "commands_found": pictures.get("commands_found", 0),
            "pictures_drawn": pictures.get("pictures_drawn", 0),
            "runtime_traces": len(pictures.get("traces", [])),
            "trace_statuses": [
                trace.get("status")
                for trace in pictures.get("traces", [])
                if isinstance(trace, Mapping)
            ],
        },
    }


def _gallery_html(batch_manifest: Mapping[str, object]) -> str:
    source = batch_manifest.get("source", {})
    summary = batch_manifest.get("summary", {})
    source = source if isinstance(source, Mapping) else {}
    summary = summary if isinstance(summary, Mapping) else {}
    lines = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        "  <title>Darkest Journey preview batch</title>",
        "  <style>",
        "    :root { color-scheme: dark; font-family: system-ui, sans-serif; }",
        "    body { margin: 2rem auto; max-width: 1500px; padding: 0 1rem; background: #141218; color: #eee; }",
        "    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1rem; }",
        "    .card { padding: .8rem; border: 1px solid #443b4d; border-radius: .5rem; background: #211c26; }",
        "    img { display: block; width: 100%; height: auto; image-rendering: pixelated; background: #101219; }",
        "    h1, h2, p { margin: .35rem 0 .7rem; }",
        "    h2 { font-size: 1rem; }",
        "    .error { color: #ff9a9a; }",
        "    code { color: #f6d78b; }",
        "  </style>",
        "</head>",
        "<body>",
        "  <h1>Darkest Journey preview batch</h1>",
        "  <p>Read-only source: <code>"
        + html.escape(str(source.get("project", "")))
        + "</code></p>",
        "  <p>Rendered: <code>"
        + html.escape(str(summary.get("rendered", 0)))
        + "</code> · Errors: <code>"
        + html.escape(str(summary.get("errors", 0)))
        + "</code></p>",
        '  <div class="grid">',
    ]
    for entry in batch_manifest.get("renders", []):
        if not isinstance(entry, Mapping):
            continue
        map_filename = html.escape(str(entry.get("map_filename", "")))
        profile = html.escape(str(entry.get("profile", "")))
        if entry.get("status") == "rendered":
            image = html.escape(str(entry.get("image", "")), quote=True)
            detail = html.escape(
                json.dumps(entry.get("summary", {}), ensure_ascii=False)
            )
            lines.extend(
                [
                    '    <article class="card">',
                    f'      <a href="{image}"><img loading="lazy" src="{image}" alt="{map_filename} — {profile}"></a>',
                    f"      <h2>{map_filename} · {profile}</h2>",
                    f"      <p><code>{detail}</code></p>",
                    "    </article>",
                ]
            )
        else:
            error = html.escape(str(entry.get("error", "unknown error")))
            lines.extend(
                [
                    '    <article class="card">',
                    f"      <h2>{map_filename} · {profile}</h2>",
                    f'      <p class="error">{error}</p>',
                    "    </article>",
                ]
            )
    lines.extend(["  </div>", "</body>", "</html>", ""])
    return "\n".join(lines)


def run_batch(
    project_dir: Path | str,
    out_dir: Path | str,
    profiles: Sequence[PreviewProfile],
    *,
    map_filenames: Optional[Sequence[str]] = None,
    all_maps: bool = False,
    representative_count: int = DEFAULT_REPRESENTATIVE_COUNT,
    rtp_dirs: Iterable[Path | str] = (),
    scale: int = 2,
    write_gallery: bool = True,
) -> dict:
    """Render selected maps for each applicable profile and write a report."""

    project_path = Path(project_dir).expanduser().resolve()
    output_path = Path(out_dir).expanduser().resolve()
    if _within(output_path, project_path):
        raise ValueError("batch output must be outside the read-only project directory")
    if scale < 1:
        raise ValueError("scale must be at least 1")
    profiles = tuple(profiles)
    rtp_dirs = tuple(rtp_dirs)
    if not profiles:
        raise ValueError("at least one preview profile is required")
    profile_names = [profile.name for profile in profiles]
    if len(set(profile_names)) != len(profile_names):
        raise ValueError("profile names must be unique")
    profile_slugs = [_safe_name(name) for name in profile_names]
    if len(set(profile_slugs)) != len(profile_slugs):
        raise ValueError("profile names must produce unique output filenames")

    metrics, discovery_errors = collect_map_metrics(project_path)
    start_map_filename = None
    if not map_filenames and not all_maps:
        try:
            start_map_filename = _project_start_map_filename(project_path)
        except (OSError, LcfParseError, ValueError) as error:
            discovery_errors.append(
                {"source": "RPG_RT.lmt", "message": str(error)}
            )
    selected_maps, selection = _resolve_map_selection(
        metrics,
        map_filenames=map_filenames,
        all_maps=all_maps,
        representative_count=representative_count,
        start_map_filename=start_map_filename,
    )
    output_path.mkdir(parents=True, exist_ok=True)
    render_entries = []
    expected = 0
    for map_filename in selected_maps:
        for profile in profiles:
            if not profile.applies_to(map_filename):
                continue
            expected += 1
            slug = _safe_name(profile.name)
            image_path = output_path / f"{Path(map_filename).stem}--{slug}.png"
            manifest_path = image_path.with_suffix(".json")
            try:
                image, manifest = render_map(
                    project_path,
                    map_filename,
                    rtp_dirs=rtp_dirs,
                    scale=scale,
                    show_lightmap=profile.lightmap,
                    show_pictures=profile.pictures,
                    runtime_traces=profile.traces,
                    picture_snapshot=profile.picture_snapshot,
                    event_state=EventState(
                        switches=dict(profile.switches),
                        variables=dict(profile.variables),
                    ),
                )
                manifest["batch"] = {
                    "profile": profile.name,
                    "selection_mode": selection["mode"],
                    "selection_reasons": next(
                        (
                            item.get("selected_by", [])
                            for item in selection["maps"]
                            if item.get("map_filename") == map_filename
                        ),
                        [],
                    ),
                }
                write_png(image_path, image)
                _write_json(manifest_path, manifest)
                render_entries.append(
                    {
                        "status": "rendered",
                        "map_filename": map_filename,
                        "profile": profile.name,
                        "image": image_path.relative_to(output_path).as_posix(),
                        "manifest": manifest_path.relative_to(output_path).as_posix(),
                        "summary": _render_summary(manifest),
                    }
                )
            except (OSError, LcfParseError, ValueError, TypeError) as error:
                render_entries.append(
                    {
                        "status": "error",
                        "map_filename": map_filename,
                        "profile": profile.name,
                        "error": str(error),
                    }
                )

    batch_manifest = {
        "schema_version": 1,
        "tool": {
            "name": "darkest-journey-preview-batch",
            "version": "0.1.0",
            "read_only": True,
        },
        "source": {
            "project": str(project_path),
            "rtp_dirs": [str(Path(path).expanduser().resolve()) for path in rtp_dirs],
        },
        "options": {
            "scale": scale,
            "gallery_written": write_gallery,
        },
        "selection": selection,
        "profiles": [_profile_manifest(profile) for profile in profiles],
        "renders": render_entries,
        "discovery_errors": discovery_errors,
        "summary": {
            "maps_available": len(metrics),
            "maps_selected": len(selected_maps),
            "renders_expected": expected,
            "rendered": sum(entry["status"] == "rendered" for entry in render_entries),
            "errors": sum(entry["status"] == "error" for entry in render_entries),
        },
    }
    manifest_path = output_path / "batch-manifest.json"
    _write_json(manifest_path, batch_manifest)
    if write_gallery:
        (output_path / "index.html").write_text(
            _gallery_html(batch_manifest),
            encoding="utf-8",
        )
    return batch_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Render a deterministic batch of RPG Maker 2000/2003 map previews "
            "without modifying the source project."
        )
    )
    parser.add_argument(
        "project_dir",
        type=Path,
        help="path to the read-only RPG Maker project directory",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help="explicit output directory outside the source project",
    )
    parser.add_argument(
        "--profile-file",
        type=Path,
        help="JSON file containing named preview profiles",
    )
    map_group = parser.add_mutually_exclusive_group()
    map_group.add_argument(
        "--map",
        dest="map_filenames",
        action="append",
        help="render this map; may be supplied more than once",
    )
    map_group.add_argument(
        "--all-maps",
        action="store_true",
        help="render every parseable MapNNNN.lmu instead of representatives",
    )
    parser.add_argument(
        "--representative-count",
        type=_positive_int,
        default=DEFAULT_REPRESENTATIVE_COUNT,
        help=f"number of representative maps (default: {DEFAULT_REPRESENTATIVE_COUNT})",
    )
    parser.add_argument(
        "--rtp-dir",
        dest="rtp_dirs",
        action="append",
        type=Path,
        default=[],
        help="optional RTP directory; may be supplied more than once",
    )
    parser.add_argument(
        "--scale",
        type=_positive_int,
        default=2,
        help="nearest-neighbor output scale (default: 2)",
    )
    parser.add_argument(
        "--no-gallery",
        action="store_true",
        help="write JSON manifests without the HTML gallery",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        profiles = (
            load_profiles(args.profile_file)
            if args.profile_file is not None
            else (PreviewProfile(name="zero-state", lightmap=False),)
        )
        manifest = run_batch(
            args.project_dir,
            args.out_dir,
            profiles,
            map_filenames=args.map_filenames,
            all_maps=args.all_maps,
            representative_count=args.representative_count,
            rtp_dirs=args.rtp_dirs,
            scale=args.scale,
            write_gallery=not args.no_gallery,
        )
    except (OSError, LcfParseError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
        return 2

    print(
        "Rendered "
        f"{manifest['summary']['rendered']}/{manifest['summary']['renders_expected']} "
        f"previews to {args.out_dir}"
    )
    print(f"Wrote {args.out_dir / 'batch-manifest.json'}")
    if not args.no_gallery:
        print(f"Wrote {args.out_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
