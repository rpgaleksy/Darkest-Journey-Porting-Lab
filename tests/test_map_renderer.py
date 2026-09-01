import binascii
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "03_rendering"))
sys.path.insert(0, str(REPO_ROOT / "02_parsing"))

from map_renderer import PNG_SIGNATURE, read_png, render_map, write_png


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
    pages = encode_int(1) + encode_int(1) + page
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
        self.assertEqual(manifest["events"]["sprites_drawn"], 1)
        self.assertEqual(manifest["events"]["missing_sprites"], [])
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


if __name__ == "__main__":
    unittest.main()
