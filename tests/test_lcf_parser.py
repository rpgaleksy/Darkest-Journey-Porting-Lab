import struct
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "02_parsing"))

from lcf_reader import LcfParseError, LcfReader, read_struct_chunks
from project_parser import parse_lmt, parse_lmu


def encode_int(value):
    """Encode one non-negative LCF compressed integer for a fixture."""

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


class LcfReaderTests(unittest.TestCase):
    def test_fixed_width_values_are_little_endian(self):
        reader = LcfReader(bytes.fromhex("34 12 fe ff 78 56 34 12"))
        self.assertEqual(reader.read_fixed_uint16(), 0x1234)
        self.assertEqual(reader.read_fixed_int16(), -2)
        self.assertEqual(reader.read_fixed_uint32(), 0x12345678)

    def test_compressed_integer_and_chunk_offsets(self):
        data = lcf_file(
            "LcfTest",
            struct_payload(chunk(0x82, encode_int(300))),
        )
        reader = LcfReader(data, source_name="fixture.lcf")
        header = reader.read_header(expected="LcfTest")
        self.assertEqual(header["value"], "LcfTest")

        parsed = read_struct_chunks(reader)
        self.assertTrue(parsed.terminated)
        self.assertEqual(len(parsed.chunks), 1)
        self.assertEqual(parsed.chunks[0].chunk_id, 0x82)
        value_reader = LcfReader(parsed.chunks[0].payload)
        self.assertEqual(value_reader.read_compressed_int(), 300)

    def test_truncated_chunk_is_rejected(self):
        reader = LcfReader(b"\x01\x05ab", source_name="truncated.lcf")
        with self.assertRaises(LcfParseError):
            reader.read_chunk()


class SemanticParserTests(unittest.TestCase):
    def test_synthetic_lmt(self):
        map_info = struct_payload(
            chunk(0x01, b"B\xfcro"),
            chunk(0x02, encode_int(3)),
            chunk(0x03, encode_int(1)),
            chunk(0x04, encode_int(1)),
            chunk(0x0C, struct_payload(chunk(0x01, b"Theme"))),
            chunk(0x33, struct.pack("<4I", 1, 2, 20, 15)),
        )
        body = (
            encode_int(1)
            + encode_int(7)
            + map_info
            + encode_int(1)
            + encode_int(7)
            + encode_int(0)
            + struct_payload(chunk(0x01, encode_int(7)))
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "RPG_RT.lmt"
            path.write_bytes(lcf_file("LcfMapTree", body))
            parsed = parse_lmt(path)

        self.assertEqual(parsed["map_count"], 1)
        self.assertEqual(parsed["maps"][0]["name"], "Büro")
        self.assertEqual(parsed["maps"][0]["parent_map"], 3)
        self.assertEqual(parsed["maps"][0]["music"]["name"], "Theme")
        self.assertEqual(parsed["maps"][0]["area_rect"], [1, 2, 20, 15])
        self.assertEqual(parsed["tree_order"], [7])
        self.assertEqual(parsed["start"]["party_map_id"], 7)

    def test_synthetic_lmu_with_event_command(self):
        condition = struct_payload(
            chunk(0x01, encode_int(1)),
            chunk(0x07, encode_int(9)),
        )
        command_payload = (
            encode_int(10110)
            + encode_int(0)
            + encode_int(5)
            + b"Hello"
            + encode_int(0)
            + b"\x00\x00\x00\x00"
        )
        page = struct_payload(
            chunk(0x02, condition),
            chunk(0x15, b"Hero"),
            chunk(0x17, encode_int(2)),
            chunk(0x19, encode_int(0)),
            chunk(0x1F, encode_int(0)),
            chunk(0x21, encode_int(1)),
            chunk(0x22, encode_int(1)),
            chunk(0x23, encode_int(0)),
            chunk(0x24, encode_int(0)),
            chunk(0x25, encode_int(3)),
            chunk(0x33, encode_int(len(command_payload))),
            chunk(0x34, command_payload),
        )
        pages = encode_int(1) + encode_int(1) + page
        event = struct_payload(
            chunk(0x01, b"NPC"),
            chunk(0x02, encode_int(4)),
            chunk(0x03, encode_int(2)),
            chunk(0x05, pages),
        )
        events = encode_int(1) + encode_int(4) + event
        body = struct_payload(
            chunk(0x01, encode_int(2)),
            chunk(0x02, encode_int(3)),
            chunk(0x03, encode_int(2)),
            chunk(0x47, struct.pack("<6h", 1, 2, 3, 4, 5, 6)),
            chunk(0x48, struct.pack("<6h", -1, -2, -3, -4, -5, -6)),
            chunk(0x51, events),
            chunk(0x5B, encode_int(7)),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Map0001.lmu"
            path.write_bytes(lcf_file("LcfMapUnit", body))
            parsed = parse_lmu(path)

        map_data = parsed["map"]
        self.assertEqual(map_data["chipset_id"], 2)
        self.assertEqual(map_data["dimensions"]["width"], 3)
        self.assertEqual(map_data["dimensions"]["height"], 2)
        self.assertEqual(map_data["lower_layer"]["tiles"], [1, 2, 3, 4, 5, 6])
        self.assertEqual(map_data["upper_layer"]["tiles"], [-1, -2, -3, -4, -5, -6])

        event = map_data["events"]["events"][0]
        self.assertEqual(event["name"], "NPC")
        page = event["pages"]["pages"][0]
        self.assertEqual(page["condition"]["flags"], 1)
        self.assertEqual(page["condition"]["actor_id"], 9)
        command = page["event_commands"]["commands"][0]
        self.assertEqual(command["code"], 10110)
        self.assertEqual(command["code_name"], "ShowMessage")
        self.assertEqual(command["string"], "Hello")
        self.assertTrue(page["event_commands"]["terminated"])

    def test_lmu_uses_rpg_maker_default_chipset_when_field_is_absent(self):
        body = struct_payload(
            chunk(0x02, encode_int(1)),
            chunk(0x03, encode_int(1)),
            chunk(0x47, struct.pack("<h", 0)),
            chunk(0x48, struct.pack("<h", 10000)),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Map0002.lmu"
            path.write_bytes(lcf_file("LcfMapUnit", body))
            parsed = parse_lmu(path)

        self.assertEqual(parsed["map"]["chipset_id"], 1)
        self.assertEqual(parsed["map"]["field_defaults_used"], ["chipset_id"])
