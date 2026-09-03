import binascii
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "03_rendering"))
sys.path.insert(0, str(REPO_ROOT / "02_parsing"))

from map_renderer import (
    PNG_SIGNATURE,
    EventState,
    read_png,
    render_map,
    select_event_page,
    write_png,
)
from render_batch import (
    PreviewProfile,
    load_profiles,
    run_batch,
    select_representative_maps,
)


def encode_int(value):
    if value < 0:
        raise ValueError("fixture helper only supports non-negative integers")
    groups = [value & 0x7F]
    value >>= 7
    while value:
        groups.append(value & 0x7F)
        value >>= 7
    groups.reverse()
    return bytes(
        group | (0x80 if index < len(groups) - 1 else 0)
        for index, group in enumerate(groups)
    )


def chunk(chunk_id, payload):
    return encode_int(chunk_id) + encode_int(len(payload)) + payload


def struct_payload(*chunks):
    return b"".join(chunks) + b"\x00"


def lcf_file(header, body):
    header_bytes = header.encode("ascii")
    return encode_int(len(header_bytes)) + header_bytes + body


def png_chunk(chunk_type, payload):
    checksum = binascii.crc32(chunk_type + payload) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", checksum)
    )


def indexed_png(width, height, palette, rectangles=()):
    indices = bytearray(width * height)
    for x, y, rectangle_width, rectangle_height, palette_index in rectangles:
        for row in range(max(0, y), min(height, y + rectangle_height)):
            start = row * width + max(0, x)
            end = row * width + min(width, x + rectangle_width)
            indices[start:end] = bytes([palette_index]) * (end - start)
    raw = b"".join(
        b"\x00" + bytes(indices[row * width:(row + 1) * width])
        for row in range(height)
    )
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0)
    plte = b"".join(bytes(color) for color in palette)
    return (
        PNG_SIGNATURE
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"PLTE", plte)
        + png_chunk(b"IDAT", zlib.compress(raw))
        + png_chunk(b"IEND", b"")
    )


def make_fixture_project(root):
    (root / "ChipSet").mkdir()
    (root / "CharSet").mkdir()
    (root / "Panorama").mkdir()
    (root / "Picture").mkdir()

    palette = [
        (7, 8, 9),
        (210, 40, 40),
        (40, 190, 70),
        (40, 80, 220),
        (230, 200, 40),
        (220, 40, 210),
        (230, 120, 40),
    ]
    chipset_rectangles = (
        (0, 3 * 16, 16, 16, 1),
        (0, 7 * 16, 16, 16, 6),
        (12 * 16, 0, 16, 16, 1),
        (3 * 16, 4 * 16, 16, 16, 2),
        (18 * 16, 8 * 16, 16, 16, 3),
        (1 * 16, 10 * 16, 16, 16, 4),
    )
    (root / "ChipSet" / "Tiles.png").write_bytes(
        indexed_png(480, 256, palette, chipset_rectangles)
    )
    charset_rectangles = ((0, 0, 24, 32, 5),)
    (root / "CharSet" / "hero.png").write_bytes(
        indexed_png(288, 256, palette, charset_rectangles)
    )
    (root / "Picture" / "Lightmap.png").write_bytes(
        indexed_png(4, 4, palette)
    )
    (root / "Panorama" / "Backdrop.png").write_bytes(
        indexed_png(16, 16, palette, ((0, 0, 16, 16, 3),))
    )

    chipset_record = struct_payload(
        chunk(0x01, b"Tiles"),
        chunk(0x02, b"Tiles"),
    )
    database_body = chunk(
        0x14,
        encode_int(1) + encode_int(1) + chipset_record,
    )
    (root / "RPG_RT.ldb").write_bytes(lcf_file("LcfDataBase", database_body))

    picture_command = (
        encode_int(11110)
        + encode_int(0)
        + encode_int(len(b"Lightmap"))
        + b"Lightmap"
        + encode_int(14)
        + b"".join(
            encode_int(value)
            for value in (1, 0, 8, 8, 0, 100, 50, 0, 100, 100, 100, 100, 0, 0)
        )
        + b"\x00\x00\x00\x00"
    )
    page = struct_payload(
        chunk(0x15, b"hero"),
        chunk(0x16, encode_int(0)),
        chunk(0x17, encode_int(0)),
        chunk(0x18, encode_int(0)),
        chunk(0x21, encode_int(0)),
        chunk(0x22, encode_int(0)),
        chunk(0x33, encode_int(len(picture_command))),
        chunk(0x34, picture_command),
    )
    conditional_page = struct_payload(
        chunk(
            0x02,
            struct_payload(
                chunk(0x01, encode_int(4)),
                chunk(0x04, encode_int(7)),
                chunk(0x05, encode_int(1)),
            ),
        ),
    )
    pages = (
        encode_int(2)
        + encode_int(1)
        + page
        + encode_int(2)
        + conditional_page
    )
    event = struct_payload(
        chunk(0x01, b"NPC"),
        chunk(0x02, encode_int(5)),
        chunk(0x03, encode_int(0)),
        chunk(0x05, pages),
    )
    events = encode_int(1) + encode_int(1) + event
    map_body = struct_payload(
        chunk(0x01, encode_int(1)),
        chunk(0x02, encode_int(6)),
        chunk(0x03, encode_int(1)),
        chunk(0x47, struct.pack("<6h", 5000, 3000, 4000, 2000, 1, 0)),
        chunk(0x48, struct.pack("<6h", 10000, 0, 0, 0, 0, 0)),
        chunk(0x51, events),
    )
    (root / "Map0001.lmu").write_bytes(lcf_file("LcfMapUnit", map_body))
    map_tree_body = (
        encode_int(1)
        + encode_int(1)
        + struct_payload(chunk(0x01, b"Start"))
        + encode_int(1)
        + encode_int(1)
        + encode_int(0)
        + struct_payload(chunk(0x01, encode_int(1)))
    )
    (root / "RPG_RT.lmt").write_bytes(lcf_file("LcfMapTree", map_tree_body))


class MapRendererTests(unittest.TestCase):
    def test_indexed_png_palette_zero_is_transparent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "indexed.png"
            path.write_bytes(
                indexed_png(
                    2,
                    1,
                    [(7, 8, 9), (200, 100, 50)],
                    ((1, 0, 1, 1, 1),),
                )
            )
            image = read_png(path)
            opaque = read_png(path, transparent_index_zero=False)

        self.assertEqual(image.pixel(0, 0), (7, 8, 9, 0))
        self.assertEqual(image.pixel(1, 0), (200, 100, 50, 255))
        self.assertEqual(opaque.pixel(0, 0), (7, 8, 9, 255))

    def test_render_map_composes_tiles_events_and_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            make_fixture_project(project)
            image, manifest = render_map(project, scale=1)
            lightmap_image, lightmap_manifest = render_map(
                project,
                scale=1,
                show_lightmap=True,
            )
            state_image, state_manifest = render_map(
                project,
                scale=1,
                show_lightmap=True,
                event_state=EventState(variables={7: 1}),
            )
            mismatch_manifest = render_map(
                project,
                scale=1,
                event_state=EventState(variables={7: 2}),
            )[1]

            output_path = project / "preview.png"
            write_png(output_path, image)
            roundtrip = read_png(output_path)

        self.assertEqual((image.width, image.height), (96, 16))
        self.assertEqual((roundtrip.width, roundtrip.height), (96, 16))
        self.assertEqual(roundtrip.pixel(20, 8), (40, 190, 70, 255))
        self.assertEqual(roundtrip.pixel(36, 8), (230, 200, 40, 255))
        self.assertEqual(roundtrip.pixel(4, 8), (40, 80, 220, 255))
        self.assertEqual(roundtrip.pixel(52, 8), (230, 120, 40, 255))
        self.assertEqual(roundtrip.pixel(68, 2), (210, 40, 40, 255))
        self.assertEqual(manifest["source"]["chipset"]["name"], "Tiles")
        self.assertEqual(manifest["tiles"]["total_tiles"], 12)
        self.assertEqual(manifest["tiles"]["rendered_tiles"], 12)
        self.assertEqual(manifest["tiles"]["unsupported_tiles"], 0)
        self.assertEqual(manifest["events"]["events_total"], 1)
        self.assertEqual(manifest["events"]["active_pages"], 1)
        self.assertEqual(manifest["events"]["sprites_drawn"], 1)
        self.assertEqual(manifest["events"]["missing_sprites"], [])
        self.assertEqual(
            manifest["events"]["page_selections"][0]["selected_page_index"],
            0,
        )
        self.assertEqual(lightmap_image.pixel(8, 8), (23, 44, 114, 255))
        self.assertNotEqual(lightmap_image.pixel(8, 8), image.pixel(8, 8))
        self.assertTrue(lightmap_manifest["pictures"]["enabled"])
        self.assertEqual(lightmap_manifest["pictures"]["commands_found"], 1)
        self.assertEqual(lightmap_manifest["pictures"]["pictures_drawn"], 1)
        self.assertEqual(
            lightmap_manifest["pictures"]["drawn_pictures"][0]["picture_name"],
            "Lightmap",
        )
        self.assertEqual(lightmap_manifest["pictures"]["missing_pictures"], [])
        self.assertNotEqual(state_image.pixel(80, 8), image.pixel(80, 8))
        self.assertEqual(state_manifest["events"]["sprites_drawn"], 0)
        self.assertEqual(
            state_manifest["events"]["page_selections"][0]["selected_page_index"],
            1,
        )
        self.assertEqual(state_manifest["pictures"]["commands_found"], 0)
        self.assertEqual(
            state_manifest["event_state"]["variables"],
            [{"id": 7, "value": 1}],
        )
        self.assertEqual(
            mismatch_manifest["events"]["page_selections"][0]["selected_page_index"],
            0,
        )

    def test_event_page_selection_uses_both_switches_and_highest_priority(self):
        event = {
            "pages": {
                "pages": [
                    {"id": 1, "index": 0, "condition": {"flags": 0}},
                    {
                        "id": 2,
                        "index": 1,
                        "condition": {
                            "flags": 3,
                            "switch_a_id": 10,
                            "switch_b_id": 11,
                        },
                    },
                ]
            }
        }

        default_page, default_decision = select_event_page(event, EventState())
        active_page, active_decision = select_event_page(
            event,
            EventState(switches={10: True, 11: True}),
        )
        zero_id_page, zero_id_decision = select_event_page(
            {
                "pages": {
                    "pages": [
                        {
                            "id": 1,
                            "index": 0,
                            "condition": {"flags": 4, "variable_value": 1},
                        }
                    ]
                }
            },
            EventState(),
        )

        self.assertEqual(default_page["index"], 0)
        self.assertEqual(default_decision["selected_page_index"], 0)
        self.assertEqual(active_page["index"], 1)
        self.assertEqual(active_decision["selected_page_index"], 1)
        self.assertEqual(
            [check["actual"] for check in active_decision["page_checks"][0]["checks"]],
            [True, True],
        )
        self.assertIsNone(zero_id_page)
        self.assertEqual(zero_id_decision["status"], "no_active_page")

    def test_render_map_supports_database_chipset_without_image_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            make_fixture_project(project)
            named_chipset = struct_payload(
                chunk(0x01, b"Tiles"),
                chunk(0x02, b"Tiles"),
            )
            empty_chipset = struct_payload(chunk(0x01, b"Empty"))
            database_body = chunk(
                0x14,
                encode_int(2)
                + encode_int(1)
                + named_chipset
                + encode_int(2)
                + empty_chipset,
            )
            (project / "RPG_RT.ldb").write_bytes(
                lcf_file("LcfDataBase", database_body)
            )
            map_body = struct_payload(
                chunk(0x01, encode_int(2)),
                chunk(0x02, encode_int(1)),
                chunk(0x03, encode_int(1)),
                chunk(0x47, struct.pack("<h", 0)),
                chunk(0x48, struct.pack("<h", 10000)),
            )
            (project / "Map0002.lmu").write_bytes(
                lcf_file("LcfMapUnit", map_body)
            )

            image, manifest = render_map(project, "Map0002.lmu", scale=1)

        self.assertEqual(image.pixel(0, 0), (0, 0, 0, 255))
        self.assertEqual(manifest["source"]["chipset"]["database_name"], "Empty")
        self.assertEqual(manifest["source"]["chipset"]["mode"], "generated_empty")
        self.assertIsNone(manifest["source"]["chipset"]["path"])
        self.assertEqual(manifest["tiles"]["rendered_tiles"], 2)
        self.assertEqual(manifest["tiles"]["unsupported_tiles"], 0)

    def test_render_map_draws_initial_map_panorama_behind_tiles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            make_fixture_project(project)
            map_body = struct_payload(
                chunk(0x01, encode_int(1)),
                chunk(0x02, encode_int(1)),
                chunk(0x03, encode_int(2)),
                chunk(0x1F, encode_int(1)),
                chunk(0x20, b"Backdrop"),
                chunk(0x22, encode_int(1)),
                chunk(0x47, struct.pack("<2h", 0, 0)),
                chunk(0x48, struct.pack("<2h", 10000, 10000)),
            )
            (project / "Map0002.lmu").write_bytes(
                lcf_file("LcfMapUnit", map_body)
            )

            image, manifest = render_map(project, "Map0002.lmu", scale=1)

        self.assertEqual((image.width, image.height), (16, 32))
        self.assertEqual(image.pixel(0, 0), (40, 80, 220, 255))
        self.assertEqual(image.pixel(0, 16), (40, 80, 220, 255))
        self.assertEqual(manifest["source"]["panorama"]["name"], "Backdrop")
        self.assertEqual(manifest["source"]["panorama"]["mode"], "image")
        self.assertEqual(manifest["source"]["panorama"]["path"], "Panorama/Backdrop.png")
        self.assertEqual(manifest["source"]["panorama"]["width"], 16)
        self.assertEqual(manifest["source"]["panorama"]["height"], 16)

    def test_event_page_selection_supports_2k3_variable_operators(self):
        cases = (
            (0, 5, 5, True),
            (1, 5, 4, True),
            (2, 5, 4, False),
            (3, 5, 4, True),
            (4, 5, 4, False),
            (5, 5, 4, True),
        )
        for operator, actual, expected, matched in cases:
            with self.subTest(operator=operator):
                event = {
                    "pages": {
                        "pages": [
                            {"id": 1, "index": 0, "condition": {"flags": 0}},
                            {
                                "id": 2,
                                "index": 1,
                                "condition": {
                                    "flags": 4,
                                    "variable_id": 7,
                                    "variable_value": expected,
                                    "compare_operator": operator,
                                },
                            },
                        ]
                    }
                }

                page, decision = select_event_page(
                    event,
                    EventState(variables={7: actual}),
                )

                self.assertEqual(page["index"], 1 if matched else 0)
                self.assertEqual(
                    decision["selected_page_index"],
                    1 if matched else 0,
                )

    def test_event_page_selection_marks_unsupported_higher_page_ambiguous(self):
        event = {
            "pages": {
                "pages": [
                    {"id": 1, "index": 0, "condition": {"flags": 0}},
                    {"id": 2, "index": 1, "condition": {"flags": 8}},
                ]
            }
        }

        page, decision = select_event_page(event, EventState())

        self.assertIsNone(page)
        self.assertEqual(decision["status"], "ambiguous")
        self.assertEqual(decision["candidate_page_index"], 0)

    def test_batch_profiles_render_manifests_and_gallery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            output = root / "batch"
            project.mkdir()
            make_fixture_project(project)
            profile_path = root / "profiles.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "profiles": [
                            {"name": "zero-state"},
                            {
                                "name": "conditional",
                                "lightmap": True,
                                "variables": {"7": 1},
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            profiles = load_profiles(profile_path)
            batch = run_batch(
                project,
                output,
                profiles,
                map_filenames=["Map0001.lmu"],
                scale=1,
            )

            self.assertEqual(batch["selection"]["mode"], "explicit")
            self.assertEqual(batch["summary"]["renders_expected"], 2)
            self.assertEqual(batch["summary"]["rendered"], 2)
            self.assertEqual(batch["summary"]["errors"], 0)
            self.assertTrue((output / "Map0001--zero-state.png").is_file())
            self.assertTrue((output / "Map0001--conditional.png").is_file())
            self.assertTrue((output / "batch-manifest.json").is_file())
            self.assertTrue((output / "index.html").is_file())
            with self.assertRaises(ValueError):
                run_batch(
                    project,
                    project / "forbidden-output",
                    profiles[:1],
                    map_filenames=["Map0001.lmu"],
                    scale=1,
                )

    def test_representative_selection_records_coverage_reasons(self):
        metrics = [
            {
                "map_filename": "Map0001.lmu",
                "area": 100,
                "events": 1,
                "conditional_pages": 0,
                "show_picture_commands": 0,
                "lightmap_commands": 0,
                "height": 10,
            },
            {
                "map_filename": "Map0002.lmu",
                "area": 200,
                "events": 9,
                "conditional_pages": 4,
                "show_picture_commands": 3,
                "lightmap_commands": 1,
                "height": 20,
            },
        ]

        selected, criteria, reasons = select_representative_maps(
            metrics,
            count=2,
            start_map_filename="Map0002.lmu",
        )

        self.assertEqual(selected, ["Map0002.lmu", "Map0001.lmu"])
        self.assertTrue(any(item["criterion"] == "start_map" for item in criteria))
        self.assertIn("start_map", reasons["Map0002.lmu"])
        self.assertIn("largest_area", reasons["Map0002.lmu"])

    def test_batch_reads_representative_start_map_from_map_tree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            output = root / "batch"
            project.mkdir()
            make_fixture_project(project)

            batch = run_batch(
                project,
                output,
                (PreviewProfile(name="zero-state"),),
                representative_count=1,
                scale=1,
            )

        self.assertEqual(batch["selection"]["maps"][0]["map_filename"], "Map0001.lmu")
        self.assertIn("start_map", batch["selection"]["maps"][0]["selected_by"])


if __name__ == "__main__":
    unittest.main()
