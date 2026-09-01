import struct
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "02_parsing"))

from resource_scanner import scan_resources


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


def png_stub(width=32, height=32):
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x00"
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x00" * 10
    )


def write_fixture_project(project):
    for directory in (
        "CharSet",
        "ChipSet",
        "Title",
        "Music",
        "mp3",
        "Panorama",
        "Picture",
    ):
        (project / directory).mkdir()

    (project / "CharSet" / "Hero.PNG").write_bytes(png_stub(48, 48))
    (project / "ChipSet" / "Tiles.png").write_bytes(png_stub())
    (project / "Title" / "Title.png").write_bytes(png_stub(320, 240))
    (project / "Music" / "Theme.link.wav").write_bytes(
        b"..\\mp3\\Theme.mp3\r\nloop\r\n"
    )
    (project / "mp3" / "Theme.mp3").write_bytes(b"ID3\x04fixture")
    (project / "Panorama" / "Backdrop.png").write_bytes(png_stub())

    actor = struct_payload(
        chunk(0x01, b"Hero"),
        chunk(0x03, b"hero"),
    )
    system = struct_payload(
        chunk(0x11, b"Title"),
        chunk(0x13, b"systemskin"),
        chunk(0x1F, struct_payload(chunk(0x01, b"Theme.link"))),
    )
    database_body = b"".join(
        (
            chunk(0x0B, encode_int(1) + encode_int(1) + actor),
            chunk(
                0x14,
                encode_int(1)
                + encode_int(1)
                + struct_payload(chunk(0x01, b"Tile Set"), chunk(0x02, b"Tiles")),
            ),
            chunk(0x16, system),
        )
    )
    (project / "RPG_RT.ldb").write_bytes(
        lcf_file("LcfDataBase", database_body)
    )

    map_info = struct_payload(
        chunk(0x01, b"Test Map"),
        chunk(0x0C, struct_payload(chunk(0x01, b"Theme.link"))),
    )
    lmt_body = (
        encode_int(1)
        + encode_int(1)
        + map_info
        + encode_int(1)
        + encode_int(1)
        + encode_int(0)
        + struct_payload(chunk(0x01, encode_int(1)))
    )
    (project / "RPG_RT.lmt").write_bytes(lcf_file("LcfMapTree", lmt_body))

    command_payload = (
        encode_int(11110)
        + encode_int(0)
        + encode_int(len(b"MissingPic"))
        + b"MissingPic"
        + encode_int(0)
        + b"\x00\x00\x00\x00"
    )
    page = struct_payload(
        chunk(0x15, b"hero"),
        chunk(0x33, encode_int(len(command_payload))),
        chunk(0x34, command_payload),
    )
    pages = encode_int(1) + encode_int(1) + page
    event = struct_payload(
        chunk(0x01, b"NPC"),
        chunk(0x02, encode_int(1)),
        chunk(0x03, encode_int(1)),
        chunk(0x05, pages),
    )
    events = encode_int(1) + encode_int(1) + event
    map_body = struct_payload(
        chunk(0x01, encode_int(1)),
        chunk(0x02, encode_int(1)),
        chunk(0x03, encode_int(1)),
        chunk(0x20, b"Backdrop"),
        chunk(0x47, struct.pack("<h", 1)),
        chunk(0x48, struct.pack("<h", 1)),
        chunk(0x51, events),
    )
    (project / "Map0001.lmu").write_bytes(
        lcf_file("LcfMapUnit", map_body)
    )


class ResourceScannerTests(unittest.TestCase):
    def test_resolves_project_assets_rtp_fallback_and_link_targets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            rtp = root / "rtp"
            project.mkdir()
            rtp.mkdir()
            write_fixture_project(project)
            (rtp / "System").mkdir()
            (rtp / "System" / "systemskin.png").write_bytes(png_stub())

            report = scan_resources(project, rtp_dirs=[rtp])

        assets = {
            (item["kind"], item["requested_name"]): item
            for item in report["assets"]
        }
        charset = assets[("charset", "hero")]
        self.assertEqual(charset["status"], "resolved")
        self.assertEqual(charset["occurrence_count"], 2)
        self.assertEqual(charset["matched_files"][0]["path"], "CharSet/Hero.PNG")

        self.assertEqual(assets[("title", "Title")]["status"], "resolved")
        system = assets[("system", "systemskin")]
        self.assertEqual(system["status"], "resolved")
        self.assertEqual(system["matched_files"][0]["root"], "rtp_1")

        music = assets[("music", "Theme.link")]
        self.assertEqual(music["status"], "resolved")
        music_file = music["matched_files"][0]
        self.assertEqual(music_file["path"], "Music/Theme.link.wav")
        self.assertEqual(music_file["format"], "rpg-maker-link")
        self.assertTrue(music_file["link"]["target_exists"])
        self.assertEqual(music_file["link"]["target_path"], "mp3/Theme.mp3")

        panorama = assets[("panorama", "Backdrop")]
        self.assertEqual(panorama["status"], "resolved")
        chipset = assets[("chipset", "Tiles")]
        self.assertEqual(chipset["status"], "resolved")
        self.assertEqual(chipset["occurrence_count"], 2)
        self.assertEqual(assets[("picture", "MissingPic")]["status"], "missing")

        files = {
            (item["root"], item["path"]): item for item in report["files"]
        }
        self.assertEqual(files[("project", "mp3/Theme.mp3")]["reference_count"], 2)
        self.assertEqual(report["coverage"]["map_files_discovered"], 1)
        self.assertEqual(report["coverage"]["map_files_parsed"], 1)
        self.assertEqual(report["coverage"]["map_events"], 1)
        self.assertEqual(report["coverage"]["map_event_commands"], 1)
        self.assertEqual(report["summary"]["missing_occurrences"], 1)
        self.assertEqual(report["summary"]["ambiguous_occurrences"], 0)


if __name__ == "__main__":
    unittest.main()
