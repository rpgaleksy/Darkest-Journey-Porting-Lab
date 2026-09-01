import struct
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "02_parsing"))

from database_parser import parse_ldb


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


class DatabaseParserTests(unittest.TestCase):
    def test_synthetic_ldb_without_root_terminator(self):
        command_payload = (
            encode_int(10110)
            + encode_int(0)
            + encode_int(5)
            + b"Hello"
            + encode_int(0)
            + b"\x00\x00\x00\x00"
        )
        actor = struct_payload(
            chunk(0x01, b"Ada"),
            chunk(0x1F, struct.pack("<6h", 10, 20, 30, 40, 50, 60)),
            chunk(0x33, struct.pack("<5H", 1, 2, 3, 4, 5)),
        )
        item = struct_payload(
            chunk(0x01, b"Key"),
            chunk(0x05, encode_int(99)),
        )
        common_event = struct_payload(
            chunk(0x01, b"Intro"),
            chunk(0x0C, encode_int(1)),
            chunk(0x0D, encode_int(3)),
            chunk(0x15, encode_int(len(command_payload))),
            chunk(0x16, command_payload),
        )
        body = b"".join(
            (
                chunk(0x0B, encode_int(1) + encode_int(1) + actor),
                chunk(0x0D, encode_int(1) + encode_int(4) + item),
                chunk(
                    0x15,
                    struct_payload(
                        chunk(0x01, b"Encounter"),
                        chunk(0x05, b"Victory"),
                    ),
                ),
                chunk(
                    0x16,
                    struct_payload(
                        chunk(0x11, b"Title"),
                        chunk(0x13, b"System"),
                    ),
                ),
                chunk(0x19, encode_int(1) + encode_int(1) + common_event),
                chunk(0x1A, encode_int(1)),
            )
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "RPG_RT.ldb"
            path.write_bytes(lcf_file("LcfDataBase", body))
            parsed = parse_ldb(path)

        database = parsed["database"]
        self.assertTrue(database["root_terminated_at_eof"])
        self.assertEqual(database["section_counts"]["actors"], 1)
        self.assertEqual(database["section_counts"]["items"], 1)
        self.assertEqual(database["section_counts"]["commonevents"], 1)
        self.assertEqual(database["actors"]["records"][0]["name"], "Ada")
        self.assertEqual(
            database["actors"]["records"][0]["parameters"]["values"],
            [[10], [20], [30], [40], [50], [60]],
        )
        self.assertEqual(
            database["actors"]["records"][0]["initial_equipment"],
            [1, 2, 3, 4, 5],
        )
        self.assertEqual(database["items"]["records"][0]["price"], 99)
        self.assertEqual(database["terms"]["encounter"], "Encounter")
        self.assertEqual(database["system"]["title_name"], "Title")

        event = database["commonevents"]["records"][0]
        self.assertEqual(event["name"], "Intro")
        self.assertEqual(event["event_commands"]["commands"][0]["string"], "Hello")
        self.assertTrue(event["event_commands"]["terminated"])
        self.assertNotIn("field_decode_errors", database)
