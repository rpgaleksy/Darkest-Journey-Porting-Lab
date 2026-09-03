"""Read-only static renderer for RPG Maker 2000/2003 map previews.

The renderer intentionally produces a diagnostic preview, not a replacement
runtime.  It decodes the indexed PNG format used by the project with the
standard library, composes the known chipset blocks, and overlays the active
event pages for an explicit preview state.  Runtime event execution, tile
substitutions, animation frames other than the selected static frame, and
passability-based z-order are kept outside this rendering pass.
"""

from __future__ import annotations

import binascii
import struct
import sys
import zlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
PARSER_DIR = REPO_ROOT / "02_parsing"
if str(PARSER_DIR) not in sys.path:
    sys.path.insert(0, str(PARSER_DIR))

from database_parser import parse_ldb
from project_parser import parse_lmu
from resource_scanner import _ResourceIndex, _candidate_names, _find_matches


TILE_SIZE = 16
CHARACTER_FRAME_WIDTH = 24
CHARACTER_FRAME_HEIGHT = 32
CHARACTER_BLOCK_WIDTH = 72
CHARACTER_BLOCK_HEIGHT = 128
PICTURE_SCREEN_WIDTH = 320
PICTURE_SCREEN_HEIGHT = 240

CONDITION_SWITCH_A = 1 << 0
CONDITION_SWITCH_B = 1 << 1
CONDITION_VARIABLE = 1 << 2
SUPPORTED_CONDITION_FLAGS = (
    CONDITION_SWITCH_A | CONDITION_SWITCH_B | CONDITION_VARIABLE
)

VARIABLE_OPERATORS = {
    0: "==",
    1: ">=",
    2: "<=",
    3: ">",
    4: "<",
    5: "!=",
}

BLOCK_RANGES = (
    ("A", 0, 2000),
    ("B", 2000, 3000),
    ("C", 3000, 3150),
    ("D", 4000, 4600),
    ("E", 5000, 5144),
    ("F", 10000, 10144),
)

Pixel = Tuple[int, int, int, int]


@dataclass(frozen=True)
class EventState:
    """Explicit RPG Maker preview state used for event-page selection."""

    switches: Mapping[int, bool] = field(default_factory=dict)
    variables: Mapping[int, int] = field(default_factory=dict)


class PngError(ValueError):
    """Raised when a PNG cannot be decoded by the diagnostic renderer."""


@dataclass
class RgbaImage:
    """Small dependency-free RGBA raster used by the renderer."""

    width: int
    height: int
    pixels: bytearray

    @classmethod
    def blank(cls, width: int, height: int, color: Pixel = (0, 0, 0, 0)) -> "RgbaImage":
        if width < 0 or height < 0:
            raise ValueError("image dimensions must not be negative")
        if len(color) != 4 or any(not 0 <= value <= 255 for value in color):
            raise ValueError("color must contain four byte values")
        return cls(width, height, bytearray(bytes(color) * (width * height)))

    def _offset(self, x: int, y: int) -> int:
        if not 0 <= x < self.width or not 0 <= y < self.height:
            raise IndexError(f"pixel coordinate outside image: ({x}, {y})")
        return (y * self.width + x) * 4

    def pixel(self, x: int, y: int) -> Pixel:
        offset = self._offset(x, y)
        return tuple(self.pixels[offset:offset + 4])  # type: ignore[return-value]

    def set_pixel(self, x: int, y: int, color: Pixel) -> None:
        offset = self._offset(x, y)
        self.pixels[offset:offset + 4] = bytes(color)

    def fill_rect(self, x: int, y: int, width: int, height: int, color: Pixel) -> None:
        if width <= 0 or height <= 0:
            return
        left = max(0, x)
        top = max(0, y)
        right = min(self.width, x + width)
        bottom = min(self.height, y + height)
        if left >= right or top >= bottom:
            return
        row = bytes(color) * (right - left)
        for row_y in range(top, bottom):
            offset = (row_y * self.width + left) * 4
            self.pixels[offset:offset + len(row)] = row

    def outline_rect(self, x: int, y: int, width: int, height: int, color: Pixel) -> None:
        self.fill_rect(x, y, width, 1, color)
        self.fill_rect(x, y + height - 1, width, 1, color)
        self.fill_rect(x, y, 1, height, color)
        self.fill_rect(x + width - 1, y, 1, height, color)

    def blit(
        self,
        source: "RgbaImage",
        source_x: int,
        source_y: int,
        width: int,
        height: int,
        destination_x: int,
        destination_y: int,
        *,
        color_key: Optional[Tuple[int, int, int]] = None,
    ) -> None:
        for y in range(height):
            source_row = source_y + y
            destination_row = destination_y + y
            if not 0 <= source_row < source.height or not 0 <= destination_row < self.height:
                continue
            for x in range(width):
                source_column = source_x + x
                destination_column = destination_x + x
                if not 0 <= source_column < source.width or not 0 <= destination_column < self.width:
                    continue
                source_offset = (source_row * source.width + source_column) * 4
                source_pixel = tuple(source.pixels[source_offset:source_offset + 4])
                if color_key is not None and source_pixel[:3] == color_key:
                    continue
                source_alpha = source_pixel[3]
                if source_alpha == 0:
                    continue
                destination_offset = (destination_row * self.width + destination_column) * 4
                if source_alpha == 255:
                    self.pixels[destination_offset:destination_offset + 4] = bytes(source_pixel)
                    continue

                destination_pixel = tuple(
                    self.pixels[destination_offset:destination_offset + 4]
                )
                destination_alpha = destination_pixel[3]
                output_alpha = source_alpha + (
                    destination_alpha * (255 - source_alpha) // 255
                )
                if output_alpha == 0:
                    continue
                output_rgb = tuple(
                    (
                        source_pixel[index] * source_alpha
                        + destination_pixel[index]
                        * destination_alpha
                        * (255 - source_alpha)
                        // 255
                    )
                    // output_alpha
                    for index in range(3)
                )
                self.pixels[destination_offset:destination_offset + 4] = bytes(
                    (*output_rgb, output_alpha)
                )

    def scale_nearest(self, scale: int) -> "RgbaImage":
        if scale < 1:
            raise ValueError("scale must be at least 1")
        if scale == 1:
            return RgbaImage(self.width, self.height, bytearray(self.pixels))
        result = RgbaImage.blank(self.width * scale, self.height * scale)
        for y in range(self.height):
            source_row = y * self.width * 4
            row = self.pixels[source_row:source_row + self.width * 4]
            expanded_row = bytearray()
            for x in range(self.width):
                pixel = row[x * 4:x * 4 + 4]
                expanded_row.extend(pixel * scale)
            for target_y in range(y * scale, (y + 1) * scale):
                offset = target_y * result.width * 4
                result.pixels[offset:offset + len(expanded_row)] = expanded_row
        return result

    def resize_nearest(self, width: int, height: int) -> "RgbaImage":
        if width < 1 or height < 1:
            raise ValueError("resized image dimensions must be positive")
        if width == self.width and height == self.height:
            return RgbaImage(self.width, self.height, bytearray(self.pixels))
        result = RgbaImage.blank(width, height)
        for target_y in range(height):
            source_y = target_y * self.height // height
            for target_x in range(width):
                source_x = target_x * self.width // width
                source_offset = (source_y * self.width + source_x) * 4
                target_offset = (target_y * width + target_x) * 4
                result.pixels[target_offset:target_offset + 4] = self.pixels[
                    source_offset:source_offset + 4
                ]
        return result

    def with_opacity(self, opacity: int) -> "RgbaImage":
        if not 0 <= opacity <= 255:
            raise ValueError("opacity must be between 0 and 255")
        result = RgbaImage(self.width, self.height, bytearray(self.pixels))
        if opacity == 255:
            return result
        for offset in range(3, len(result.pixels), 4):
            result.pixels[offset] = result.pixels[offset] * opacity // 255
        return result


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_chunks(data: bytes) -> Iterable[Tuple[bytes, bytes]]:
    if not data.startswith(PNG_SIGNATURE):
        raise PngError("file does not start with a PNG signature")
    position = len(PNG_SIGNATURE)
    while position < len(data):
        if position + 12 > len(data):
            raise PngError("truncated PNG chunk header")
        length = struct.unpack(">I", data[position:position + 4])[0]
        chunk_type = data[position + 4:position + 8]
        payload_start = position + 8
        payload_end = payload_start + length
        crc_end = payload_end + 4
        if crc_end > len(data):
            raise PngError("truncated PNG chunk payload")
        payload = data[payload_start:payload_end]
        expected_crc = struct.unpack(">I", data[payload_end:crc_end])[0]
        actual_crc = binascii.crc32(chunk_type + payload) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise PngError(f"invalid CRC in PNG chunk {chunk_type!r}")
        yield chunk_type, payload
        position = crc_end
        if chunk_type == b"IEND":
            return
    raise PngError("PNG has no IEND chunk")


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def read_png(
    path: Path | str,
    *,
    transparent_index_zero: bool = True,
) -> RgbaImage:
    """Read the 8-bit non-interlaced PNG variants used by RPG Maker assets.

    Chipsets and charsets use palette index 0 as their transparent color. For
    Pictures, the ShowPicture command controls this behavior, so callers can
    disable it with ``transparent_index_zero=False``.
    """

    data = Path(path).read_bytes()
    header = None
    palette = None
    transparency = None
    idat: List[bytes] = []
    for chunk_type, payload in _png_chunks(data):
        if chunk_type == b"IHDR":
            if len(payload) != 13:
                raise PngError("PNG IHDR must contain 13 bytes")
            header = struct.unpack(">IIBBBBB", payload)
        elif chunk_type == b"PLTE":
            if len(payload) % 3:
                raise PngError("PNG palette length is not divisible by three")
            palette = [
                tuple(payload[offset:offset + 3])
                for offset in range(0, len(payload), 3)
            ]
        elif chunk_type == b"tRNS":
            transparency = payload
        elif chunk_type == b"IDAT":
            idat.append(payload)

    if header is None:
        raise PngError("PNG has no IHDR chunk")
    width, height, bit_depth, color_type, compression, filter_method, interlace = header
    if width < 1 or height < 1:
        raise PngError("PNG dimensions must be positive")
    if bit_depth != 8 or compression != 0 or filter_method != 0 or interlace != 0:
        raise PngError(
            "renderer supports only 8-bit, non-interlaced PNG images"
        )
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise PngError(f"unsupported PNG color type {color_type}")
    if color_type == 3 and not palette:
        raise PngError("indexed PNG has no palette")
    try:
        decoded = zlib.decompress(b"".join(idat))
    except zlib.error as error:
        raise PngError(f"could not decompress PNG image data: {error}") from error

    row_bytes = width * channels
    expected_bytes = height * (row_bytes + 1)
    if len(decoded) < expected_bytes:
        raise PngError("PNG image data is truncated")
    rows: List[bytearray] = []
    position = 0
    previous = bytearray(row_bytes)
    for _ in range(height):
        filter_type = decoded[position]
        position += 1
        row = bytearray(decoded[position:position + row_bytes])
        position += row_bytes
        for index in range(row_bytes):
            left = row[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                row[index] = (row[index] + left) & 0xFF
            elif filter_type == 2:
                row[index] = (row[index] + above) & 0xFF
            elif filter_type == 3:
                row[index] = (row[index] + ((left + above) // 2)) & 0xFF
            elif filter_type == 4:
                row[index] = (row[index] + _paeth(left, above, upper_left)) & 0xFF
            elif filter_type != 0:
                raise PngError(f"unsupported PNG filter type {filter_type}")
        rows.append(row)
        previous = row

    image = RgbaImage.blank(width, height)
    transparent_gray = None
    transparent_rgb = None
    if transparency is not None and color_type == 0 and len(transparency) == 2:
        transparent_gray = struct.unpack(">H", transparency)[0] & 0xFF
    elif transparency is not None and color_type == 2 and len(transparency) == 6:
        transparent_rgb = tuple(
            struct.unpack(">HHH", transparency)[index] & 0xFF
            for index in range(3)
        )

    for y, row in enumerate(rows):
        for x in range(width):
            offset = x * channels
            if color_type == 0:
                value = row[offset]
                alpha = 0 if value == transparent_gray else 255
                color = (value, value, value, alpha)
            elif color_type == 2:
                rgb = tuple(row[offset:offset + 3])
                alpha = 0 if rgb == transparent_rgb else 255
                color = (*rgb, alpha)
            elif color_type == 3:
                palette_index = row[offset]
                if palette_index >= len(palette or []):
                    raise PngError("PNG palette index is out of range")
                rgb = palette[palette_index]
                if transparency is not None and palette_index < len(transparency):
                    alpha = transparency[palette_index]
                else:
                    # RPG Maker's indexed assets reserve palette index 0 for
                    # transparency.  The transparent RGB value need not be
                    # the pixel at (0, 0), so a first-pixel color key is not
                    # equivalent here.
                    alpha = (
                        0
                        if transparent_index_zero and palette_index == 0
                        else 255
                    )
                color = (*rgb, alpha)
            elif color_type == 4:
                value, alpha = row[offset:offset + 2]
                color = (value, value, value, alpha)
            else:
                color = tuple(row[offset:offset + 4])  # type: ignore[assignment]
            image.set_pixel(x, y, color)
    return image


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    crc = binascii.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", crc)


def write_png(path: Path | str, image: RgbaImage) -> None:
    """Write an RGBA PNG to an explicit output path."""

    if image.width < 1 or image.height < 1:
        raise ValueError("image dimensions must be positive")
    if len(image.pixels) != image.width * image.height * 4:
        raise ValueError("RGBA pixel buffer does not match image dimensions")
    raw = b"".join(
        b"\x00" + bytes(image.pixels[row * image.width * 4:(row + 1) * image.width * 4])
        for row in range(image.height)
    )
    ihdr = struct.pack(">IIBBBBB", image.width, image.height, 8, 6, 0, 0, 0)
    payload = (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, level=6))
        + _png_chunk(b"IEND", b"")
    )
    Path(path).write_bytes(payload)


# The tables describe the standard 2k/2k3 chipset quadrant layouts.  They
# are kept as data so the renderer remains deterministic and easy to compare
# with the corresponding runtime implementation.
A_SUBTILES: Tuple[Tuple[Tuple[Optional[int], Optional[int]], Tuple[Optional[int], Optional[int]]], ...] = (
    ((None, None), (None, None)),
    ((3, None), (None, None)),
    ((None, 3), (None, None)),
    ((3, 3), (None, None)),
    ((None, None), (None, 3)),
    ((3, None), (None, 3)),
    ((None, 3), (None, 3)),
    ((3, 3), (None, 3)),
    ((None, None), (3, None)),
    ((3, None), (3, None)),
    ((None, 3), (3, None)),
    ((3, 3), (3, None)),
    ((None, None), (3, 3)),
    ((3, None), (3, 3)),
    ((None, 3), (3, 3)),
    ((3, 3), (3, 3)),
    ((1, None), (1, None)),
    ((1, 3), (1, None)),
    ((1, None), (1, 3)),
    ((1, 3), (1, 3)),
    ((2, 2), (None, None)),
    ((2, 2), (None, 3)),
    ((2, 2), (3, None)),
    ((2, 2), (3, 3)),
    ((None, 1), (None, 1)),
    ((None, 1), (3, 1)),
    ((3, 1), (None, 1)),
    ((3, 1), (3, 1)),
    ((None, None), (2, 2)),
    ((3, None), (2, 2)),
    ((None, 3), (2, 2)),
    ((3, 3), (2, 2)),
    ((1, 1), (1, 1)),
    ((2, 2), (2, 2)),
    ((0, 2), (1, None)),
    ((0, 2), (1, 3)),
    ((2, 0), (None, 1)),
    ((2, 0), (3, 1)),
    ((None, 1), (2, 0)),
    ((3, 1), (2, 0)),
    ((1, None), (0, 2)),
    ((1, 3), (0, 2)),
    ((0, 0), (1, 1)),
    ((0, 2), (0, 2)),
    ((1, 1), (0, 0)),
    ((2, 0), (2, 0)),
    ((0, 0), (0, 0)),
)


D_SUBTILES = (
    (((1, 2), (1, 2)), ((1, 2), (1, 2))),
    (((2, 0), (1, 2)), ((1, 2), (1, 2))),
    (((1, 2), (2, 0)), ((1, 2), (1, 2))),
    (((2, 0), (2, 0)), ((1, 2), (1, 2))),
    (((1, 2), (1, 2)), ((1, 2), (2, 0))),
    (((2, 0), (1, 2)), ((1, 2), (2, 0))),
    (((1, 2), (2, 0)), ((1, 2), (2, 0))),
    (((2, 0), (2, 0)), ((1, 2), (2, 0))),
    (((1, 2), (1, 2)), ((2, 0), (1, 2))),
    (((2, 0), (1, 2)), ((2, 0), (1, 2))),
    (((1, 2), (2, 0)), ((2, 0), (1, 2))),
    (((2, 0), (2, 0)), ((2, 0), (1, 2))),
    (((1, 2), (1, 2)), ((2, 0), (2, 0))),
    (((2, 0), (1, 2)), ((2, 0), (2, 0))),
    (((1, 2), (2, 0)), ((2, 0), (2, 0))),
    (((2, 0), (2, 0)), ((2, 0), (2, 0))),
    (((0, 2), (0, 2)), ((0, 2), (0, 2))),
    (((0, 2), (2, 0)), ((0, 2), (0, 2))),
    (((0, 2), (0, 2)), ((0, 2), (2, 0))),
    (((0, 2), (2, 0)), ((0, 2), (2, 0))),
    (((1, 1), (1, 1)), ((1, 1), (1, 1))),
    (((1, 1), (1, 1)), ((1, 1), (2, 0))),
    (((1, 1), (1, 1)), ((2, 0), (1, 1))),
    (((1, 1), (1, 1)), ((2, 0), (2, 0))),
    (((2, 2), (2, 2)), ((2, 2), (2, 2))),
    (((2, 2), (2, 2)), ((2, 0), (2, 2))),
    (((2, 0), (2, 2)), ((2, 2), (2, 2))),
    (((2, 0), (2, 2)), ((2, 0), (2, 2))),
    (((1, 3), (1, 3)), ((1, 3), (1, 3))),
    (((2, 0), (1, 3)), ((1, 3), (1, 3))),
    (((1, 3), (2, 0)), ((1, 3), (1, 3))),
    (((2, 0), (2, 0)), ((1, 3), (1, 3))),
    (((0, 2), (2, 2)), ((0, 2), (2, 2))),
    (((1, 1), (1, 1)), ((1, 3), (1, 3))),
    (((0, 1), (0, 1)), ((0, 1), (0, 1))),
    (((0, 1), (0, 1)), ((0, 1), (2, 0))),
    (((2, 1), (2, 1)), ((2, 1), (2, 1))),
    (((2, 1), (2, 1)), ((2, 0), (2, 1))),
    (((2, 3), (2, 3)), ((2, 3), (2, 3))),
    (((2, 0), (2, 3)), ((2, 3), (2, 3))),
    (((0, 3), (0, 3)), ((0, 3), (0, 3))),
    (((0, 3), (2, 0)), ((0, 3), (0, 3))),
    (((0, 1), (2, 1)), ((0, 1), (2, 1))),
    (((0, 1), (0, 1)), ((0, 3), (0, 3))),
    (((0, 3), (2, 3)), ((0, 3), (2, 3))),
    (((2, 1), (2, 1)), ((2, 3), (2, 3))),
    (((0, 1), (2, 1)), ((0, 3), (2, 3))),
    (((1, 2), (1, 2)), ((1, 2), (1, 2))),
    (((1, 2), (1, 2)), ((1, 2), (1, 2))),
    (((0, 0), (0, 0)), ((0, 0), (0, 0))),
)


def _tile_block(tile_id: object) -> str:
    if not isinstance(tile_id, int):
        return "invalid"
    for name, start, end in BLOCK_RANGES:
        if start <= tile_id < end:
            return name
    return "unknown"


def _copy_quarter(
    destination: RgbaImage,
    source: RgbaImage,
    source_tile_x: int,
    source_tile_y: int,
    destination_quarter_x: int,
    destination_quarter_y: int,
) -> None:
    destination.blit(
        source,
        source_tile_x * TILE_SIZE + destination_quarter_x * (TILE_SIZE // 2),
        source_tile_y * TILE_SIZE + destination_quarter_y * (TILE_SIZE // 2),
        TILE_SIZE // 2,
        TILE_SIZE // 2,
        destination_quarter_x * (TILE_SIZE // 2),
        destination_quarter_y * (TILE_SIZE // 2),
    )


def _tile_from_chipset(
    source: RgbaImage,
    tile_id: int,
    *,
    animation_frame: int = 0,
) -> Optional[RgbaImage]:
    """Compose one map tile using the standard 2k/2k3 chipset blocks."""

    if not isinstance(tile_id, int):
        return None
    tile = RgbaImage.blank(TILE_SIZE, TILE_SIZE)

    if 0 <= tile_id < 3000:
        block = tile_id // 1000
        b_subtile = (tile_id - block * 1000) // 50
        a_subtile = tile_id - block * 1000 - b_subtile * 50
        if block not in (0, 1, 2) or not 0 <= b_subtile < 16 or not 0 <= a_subtile < len(A_SUBTILES):
            return None
        quadrants = A_SUBTILES[a_subtile]
        source_coordinates: List[List[Tuple[int, int]]] = [
            [(0, 0), (0, 0)],
            [(0, 0), (0, 0)],
        ]
        for quarter_y in range(2):
            for quarter_x in range(2):
                a_value = quadrants[quarter_y][quarter_x]
                if a_value is not None:
                    source_coordinates[quarter_y][quarter_x] = (
                        animation_frame + (3 if block == 1 else 0),
                        a_value,
                    )
                else:
                    b_value = (b_subtile >> (quarter_y * 2 + quarter_x)) & 1
                    if block == 2:
                        b_value ^= 3
                    source_coordinates[quarter_y][quarter_x] = (
                        animation_frame,
                        4 + b_value,
                    )
        if b_subtile != 0 and a_subtile != 0:
            for quarter_y in range(2):
                for quarter_x in range(2):
                    b_value = (b_subtile >> (quarter_y * 2 + quarter_x)) & 1
                    if block == 2:
                        b_value *= 2
                    if b_value != 0:
                        source_coordinates[quarter_y][quarter_x] = (
                            animation_frame,
                            4 + b_value,
                        )
        for quarter_y in range(2):
            for quarter_x in range(2):
                source_x, source_y = source_coordinates[quarter_y][quarter_x]
                _copy_quarter(
                    tile,
                    source,
                    source_x,
                    source_y,
                    quarter_x,
                    quarter_y,
                )
        return tile

    if 3000 <= tile_id < 3150:
        column = 3 + (tile_id - 3000) // 50
        row = 4 + animation_frame
        tile.blit(
            source,
            column * TILE_SIZE,
            row * TILE_SIZE,
            TILE_SIZE,
            TILE_SIZE,
            0,
            0,
        )
        return tile

    if 4000 <= tile_id < 4600:
        block = (tile_id - 4000) // 50
        subtile = (tile_id - 4000) % 50
        if not 0 <= block < 12 or not 0 <= subtile < len(D_SUBTILES):
            return None
        if block < 4:
            block_x = (block % 2) * 3
            block_y = 8 + (block // 2) * 4
        else:
            block_x = 6 + (block % 2) * 3
            block_y = ((block - 4) // 2) * 4
        for quarter_y in range(2):
            for quarter_x in range(2):
                source_x, source_y = D_SUBTILES[subtile][quarter_y][quarter_x]
                _copy_quarter(
                    tile,
                    source,
                    block_x + source_x,
                    block_y + source_y,
                    quarter_x,
                    quarter_y,
                )
        return tile

    if 5000 <= tile_id < 5144:
        direct_id = tile_id - 5000
        if direct_id < 96:
            column = 12 + direct_id % 6
            row = direct_id // 6
        else:
            column = 18 + (direct_id - 96) % 6
            row = (direct_id - 96) // 6
        tile.blit(
            source,
            column * TILE_SIZE,
            row * TILE_SIZE,
            TILE_SIZE,
            TILE_SIZE,
            0,
            0,
        )
        return tile

    if 10000 <= tile_id < 10144:
        direct_id = tile_id - 10000
        if direct_id < 48:
            column = 18 + direct_id % 6
            row = 8 + direct_id // 6
        else:
            column = 24 + (direct_id - 48) % 6
            row = (direct_id - 48) // 6
        tile.blit(
            source,
            column * TILE_SIZE,
            row * TILE_SIZE,
            TILE_SIZE,
            TILE_SIZE,
            0,
            0,
        )
        return tile

    return None


def _resolve_asset(
    indexes: Sequence[_ResourceIndex],
    kind: str,
    requested_name: object,
) -> Tuple[Optional[Path], Optional[dict], int]:
    if not isinstance(requested_name, str) or not requested_name.strip():
        return None, None, 0
    candidates = _candidate_names(requested_name.strip(), kind)
    for index in indexes:
        matches = _find_matches(index, kind, candidates)
        if not matches:
            continue
        descriptor = matches[0]
        return index.root / descriptor["path"], descriptor, len(matches)
    return None, None, 0


def _normalize_event_state(state: Optional[EventState]) -> EventState:
    if state is None:
        return EventState()
    if not isinstance(state, EventState):
        raise TypeError("event_state must be an EventState instance")
    if not isinstance(state.switches, Mapping):
        raise TypeError("event_state.switches must be a mapping")
    if not isinstance(state.variables, Mapping):
        raise TypeError("event_state.variables must be a mapping")

    switches = {}
    for switch_id, value in state.switches.items():
        if isinstance(switch_id, bool) or not isinstance(switch_id, int) or switch_id < 1:
            raise ValueError("event switch IDs must be positive integers")
        if not isinstance(value, bool):
            raise ValueError("event switch values must be booleans")
        switches[switch_id] = value

    variables = {}
    for variable_id, value in state.variables.items():
        if isinstance(variable_id, bool) or not isinstance(variable_id, int) or variable_id < 1:
            raise ValueError("event variable IDs must be positive integers")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("event variable values must be integers")
        variables[variable_id] = value

    return EventState(
        switches=dict(sorted(switches.items())),
        variables=dict(sorted(variables.items())),
    )


def _variable_matches(actual: int, expected: int, operator: int) -> bool:
    if operator == 0:
        return actual == expected
    if operator == 1:
        return actual >= expected
    if operator == 2:
        return actual <= expected
    if operator == 3:
        return actual > expected
    if operator == 4:
        return actual < expected
    if operator == 5:
        return actual != expected
    return False


def _page_condition_result(
    page: Mapping[str, object],
    state: EventState,
) -> dict:
    condition = page.get("condition", {})
    if condition is None:
        condition = {}
    if not isinstance(condition, Mapping):
        return {
            "result": "invalid",
            "reason": "event page condition is not a mapping",
            "checks": [],
        }
    flags = condition.get("flags", 0)
    if isinstance(flags, bool) or not isinstance(flags, int) or flags < 0:
        return {
            "result": "invalid",
            "reason": "event page condition flags are not a non-negative integer",
            "checks": [],
        }
    unsupported_flags = flags & ~SUPPORTED_CONDITION_FLAGS
    if unsupported_flags:
        return {
            "result": "unsupported",
            "reason": f"unsupported event page condition flags: {unsupported_flags}",
            "condition_flags": flags,
            "unsupported_flags": unsupported_flags,
            "checks": [],
        }

    checks = []
    for flag, field_name, label in (
        (CONDITION_SWITCH_A, "switch_a_id", "switch_a"),
        (CONDITION_SWITCH_B, "switch_b_id", "switch_b"),
    ):
        if not flags & flag:
            continue
        switch_id = condition.get(field_name, 0)
        if isinstance(switch_id, bool) or not isinstance(switch_id, int) or switch_id < 0:
            return {
                "result": "invalid",
                "reason": f"{label} has no non-negative integer ID",
                "condition_flags": flags,
                "checks": checks,
            }
        actual = state.switches.get(switch_id, False)
        checks.append(
            {
                "kind": label,
                "id": switch_id,
                "actual": actual,
                "expected": True,
                "matched": actual,
            }
        )

    if flags & CONDITION_VARIABLE:
        variable_id = condition.get("variable_id", 0)
        expected = condition.get("variable_value", 0)
        operator = condition.get("compare_operator", 0)
        if isinstance(variable_id, bool) or not isinstance(variable_id, int) or variable_id < 0:
            return {
                "result": "invalid",
                "reason": "variable condition has no non-negative integer ID",
                "condition_flags": flags,
                "checks": checks,
            }
        if isinstance(expected, bool) or not isinstance(expected, int):
            return {
                "result": "invalid",
                "reason": "variable condition has no integer comparison value",
                "condition_flags": flags,
                "checks": checks,
            }
        if isinstance(operator, bool) or not isinstance(operator, int) or operator not in VARIABLE_OPERATORS:
            return {
                "result": "unsupported",
                "reason": f"unsupported variable comparison operator: {operator!r}",
                "condition_flags": flags,
                "checks": checks,
            }
        actual = state.variables.get(variable_id, 0)
        checks.append(
            {
                "kind": "variable",
                "id": variable_id,
                "actual": actual,
                "operator": VARIABLE_OPERATORS[operator],
                "expected": expected,
                "matched": _variable_matches(actual, expected, operator),
            }
        )

    return {
        "result": "matched" if all(check["matched"] for check in checks) else "not_matched",
        "condition_flags": flags,
        "checks": checks,
    }


def select_event_page(
    event: Mapping[str, object],
    state: EventState,
) -> Tuple[Optional[Mapping[str, object]], dict]:
    """Select the highest-priority page whose supported conditions are met."""

    pages_data = event.get("pages")
    pages = pages_data.get("pages", []) if isinstance(pages_data, Mapping) else []
    if not isinstance(pages, list):
        pages = []
    page_checks = []
    uncertain_pages = []
    for page in reversed(pages):
        if not isinstance(page, Mapping):
            result = {
                "result": "invalid",
                "reason": "event page is not a mapping",
                "checks": [],
            }
            page_index = None
            page_id = None
        else:
            result = _page_condition_result(page, state)
            page_index = page.get("index")
            page_id = page.get("id")
        check = {
            "page_index": page_index,
            "page_id": page_id,
            **result,
        }
        page_checks.append(check)
        if result["result"] in ("unsupported", "invalid"):
            uncertain_pages.append(check)
            continue
        if result["result"] != "matched":
            continue
        if uncertain_pages:
            return None, {
                "status": "ambiguous",
                "selected_page_index": None,
                "selected_page_id": None,
                "candidate_page_index": page_index,
                "candidate_page_id": page_id,
                "page_checks": page_checks,
            }
        return page, {
            "status": "selected",
            "selected_page_index": page_index,
            "selected_page_id": page_id,
            "page_checks": page_checks,
        }

    return None, {
        "status": "ambiguous" if uncertain_pages else "no_active_page",
        "selected_page_index": None,
        "selected_page_id": None,
        "page_checks": page_checks,
    }


def _event_page_selections(
    map_data: Mapping[str, object],
    state: EventState,
) -> List[dict]:
    events_data = map_data.get("events", {})
    events = events_data.get("events", []) if isinstance(events_data, Mapping) else []
    result = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        page, decision = select_event_page(event, state)
        result.append(
            {
                "event": event,
                "page": page,
                "decision": decision,
            }
        )
    return result


def _picture_commands(event_page_selections: Sequence[Mapping[str, object]]) -> List[dict]:
    """Collect ShowPicture commands from the selected event pages."""

    result = []
    for selection in event_page_selections:
        event = selection.get("event")
        page = selection.get("page")
        if not isinstance(event, Mapping):
            continue
        if not isinstance(page, Mapping):
            continue
        commands_data = page.get("event_commands", {})
        commands = (
            commands_data.get("commands", [])
            if isinstance(commands_data, Mapping)
            else []
        )
        for command_index, command in enumerate(commands):
            if not isinstance(command, Mapping) or command.get("code") != 11110:
                continue
            result.append(
                {
                    "event_id": event.get("id"),
                    "event_name": event.get("name"),
                    "page_index": page.get("index"),
                    "command_index": command_index,
                    "command": command,
                }
            )
    return result


def _signed_int32(value: int) -> int:
    if value >= 0x80000000:
        return value - 0x100000000
    return value


def _parse_show_picture(command: Mapping[str, object]) -> Optional[dict]:
    parameters = command.get("parameters")
    if not isinstance(parameters, list) or len(parameters) < 14:
        return None
    if not all(isinstance(value, int) for value in parameters[:14]):
        return None
    return {
        "picture_id": parameters[0],
        "position_mode": parameters[1] & 0xFF,
        "x": _signed_int32(parameters[2]),
        "y": _signed_int32(parameters[3]),
        "fixed_to_map": parameters[4] > 0,
        "zoom": max(0, min(parameters[5], 2000)),
        "top_transparency": max(0, min(parameters[6], 100)),
        "use_transparent_color": parameters[7] > 0,
        "tone": parameters[8:12],
        "effect_mode": parameters[12],
        "effect_power": parameters[13],
    }


def _lightmap_name(name: object) -> bool:
    return isinstance(name, str) and "lightmap" in name.casefold()


def _unsupported_tile(
    tile_id: object,
    *,
    background: Pixel = (28, 24, 36, 255),
    foreground: Pixel = (224, 62, 148, 255),
) -> RgbaImage:
    tile = RgbaImage.blank(TILE_SIZE, TILE_SIZE, background)
    for y in range(0, TILE_SIZE, 4):
        for x in range(0, TILE_SIZE, 4):
            if ((x // 4) + (y // 4)) % 2 == 0:
                tile.fill_rect(x, y, 4, 4, foreground)
    tile.outline_rect(0, 0, TILE_SIZE, TILE_SIZE, (255, 229, 105, 255))
    return tile


def render_map(
    project_dir: Path | str,
    map_filename: str = "Map0001.lmu",
    *,
    rtp_dirs: Iterable[Path | str] = (),
    scale: int = 2,
    show_events: bool = True,
    show_lightmap: bool = False,
    event_state: Optional[EventState] = None,
) -> Tuple[RgbaImage, dict]:
    """Render one map to an RGBA image and return image plus manifest data."""

    if scale < 1:
        raise ValueError("scale must be at least 1")
    project_path = Path(project_dir).expanduser().resolve()
    if not project_path.is_dir():
        raise FileNotFoundError(f"project directory does not exist: {project_path}")
    map_path = project_path / map_filename
    if not map_path.is_file():
        raise FileNotFoundError(f"map file does not exist: {map_path}")

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
    database_report = parse_ldb(project_path / "RPG_RT.ldb")
    map_report = parse_lmu(map_path)
    database = database_report["database"]
    map_data = map_report["map"]
    preview_state = _normalize_event_state(event_state)
    event_page_selections = _event_page_selections(map_data, preview_state)

    chipset_records = {
        record["id"]: record
        for record in database.get("chipsets", {}).get("records", [])
        if isinstance(record, Mapping) and isinstance(record.get("id"), int)
    }
    chipset_id = map_data.get("chipset_id")
    chipset_record = chipset_records.get(chipset_id)
    if chipset_record is None:
        raise ValueError(
            f"map {map_filename} references unknown chipset id {chipset_id!r}"
        )
    chipset_name = chipset_record.get("chipset_name")
    if isinstance(chipset_name, str) and chipset_name.strip():
        chipset_path, chipset_descriptor, chipset_matches = _resolve_asset(
            indexes,
            "chipset",
            chipset_name,
        )
        if chipset_path is None or chipset_descriptor is None:
            raise ValueError(
                f"could not resolve chipset for map {map_filename}: "
                f"id={chipset_id!r}, name={chipset_name!r}"
            )
        if chipset_matches > 1:
            raise ValueError(
                f"chipset reference {chipset_name!r} is ambiguous in "
                f"{chipset_descriptor['root']}"
            )
        chipset = read_png(chipset_path)
        if chipset.width < 480 or chipset.height < 256:
            raise ValueError(
                f"chipset image is smaller than the standard 480x256 raster: "
                f"{chipset_path} ({chipset.width}x{chipset.height})"
            )
        chipset_mode = "image"
    elif chipset_name in (None, ""):
        chipset_path = None
        chipset_descriptor = {"root": None, "path": None}
        chipset = RgbaImage.blank(480, 256)
        chipset_mode = "generated_empty"
    else:
        raise ValueError(
            f"chipset {chipset_id!r} has an invalid image name: {chipset_name!r}"
        )

    dimensions = map_data.get("dimensions", {})
    if not isinstance(dimensions, Mapping):
        raise ValueError(f"map {map_filename} has no usable dimensions")
    width = dimensions.get("width")
    height = dimensions.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width < 1 or height < 1:
        raise ValueError(f"map {map_filename} has invalid dimensions: {dimensions!r}")

    canvas_background = (
        (0, 0, 0, 255)
        if chipset_mode == "generated_empty"
        else (16, 18, 25, 255)
    )
    canvas = RgbaImage.blank(width * TILE_SIZE, height * TILE_SIZE, canvas_background)
    tile_statistics = {
        "total_tiles": width * height * 2,
        "by_block": Counter(),
        "rendered_tiles": 0,
        "unsupported_tiles": 0,
        "unsupported_tile_ids": set(),
    }
    layers = (
        ("lower", map_data.get("lower_layer", {}).get("tiles", [])),
        ("upper", map_data.get("upper_layer", {}).get("tiles", [])),
    )
    for _layer_name, raw_tiles in layers:
        tiles = raw_tiles if isinstance(raw_tiles, list) else []
        for index in range(width * height):
            tile_id = tiles[index] if index < len(tiles) else None
            tile_statistics["by_block"][_tile_block(tile_id)] += 1
            x = index % width
            y = index // width
            tile = _tile_from_chipset(chipset, tile_id)
            if tile is None:
                tile_statistics["unsupported_tiles"] += 1
                if isinstance(tile_id, int):
                    tile_statistics["unsupported_tile_ids"].add(tile_id)
                tile = _unsupported_tile(tile_id)
            else:
                tile_statistics["rendered_tiles"] += 1
            canvas.blit(tile, 0, 0, TILE_SIZE, TILE_SIZE, x * TILE_SIZE, y * TILE_SIZE)

    event_statistics = {
        "enabled": show_events,
        "events_total": len(event_page_selections),
        "active_pages": sum(
            1 for selection in event_page_selections if selection["page"] is not None
        ),
        "ambiguous_events": [],
        "page_selections": [],
        "pages_with_graphics": 0,
        "sprites_drawn": 0,
        "missing_sprites": [],
        "ambiguous_sprites": [],
        "invalid_sprites": [],
    }
    for selection in event_page_selections:
        event = selection["event"]
        decision = selection["decision"]
        event_identity = {
            "event_id": event.get("id"),
            "event_name": event.get("name"),
        }
        event_statistics["page_selections"].append(
            {**event_identity, **decision}
        )
        if decision["status"] == "ambiguous":
            event_statistics["ambiguous_events"].append(event_identity)

    if show_events:
        charset_cache = {}
        for selection in event_page_selections:
            event = selection["event"]
            page = selection["page"]
            if not isinstance(event, Mapping):
                continue
            if not isinstance(page, Mapping):
                continue
            character_name = page.get("character_name")
            if not isinstance(character_name, str) or not character_name.strip():
                continue
            event_statistics["pages_with_graphics"] += 1
            charset_path, charset_descriptor, charset_matches = _resolve_asset(
                indexes,
                "charset",
                character_name,
            )
            event_identity = {
                "event_id": event.get("id"),
                "event_name": event.get("name"),
                "page_index": page.get("index"),
                "character_name": character_name,
            }
            if charset_path is None or charset_descriptor is None:
                event_statistics["missing_sprites"].append(event_identity)
                continue
            if charset_matches > 1:
                event_statistics["ambiguous_sprites"].append(event_identity)
            try:
                charset_key = str(charset_path)
                charset = charset_cache.get(charset_key)
                if charset is None:
                    charset = read_png(charset_path)
                    charset_cache[charset_key] = charset
            except (OSError, PngError) as error:
                event_statistics["invalid_sprites"].append(
                    {**event_identity, "message": str(error)}
                )
                continue
            character_index = page.get("character_index", 0)
            direction = page.get("character_direction", 0)
            pattern = page.get("character_pattern", 0)
            if not isinstance(character_index, int):
                character_index = 0
            if not isinstance(direction, int):
                direction = 0
            if not isinstance(pattern, int):
                pattern = 0
            character_index = max(0, min(3, character_index))
            direction = max(0, min(3, direction))
            pattern = max(0, min(2, pattern))
            source_x = character_index * CHARACTER_BLOCK_WIDTH + pattern * CHARACTER_FRAME_WIDTH
            source_y = direction * CHARACTER_FRAME_HEIGHT
            if source_x + CHARACTER_FRAME_WIDTH > charset.width or source_y + CHARACTER_FRAME_HEIGHT > charset.height:
                event_statistics["invalid_sprites"].append(
                    {
                        **event_identity,
                        "message": "character frame is outside charset image",
                    }
                )
                continue
            event_x = event.get("x")
            event_y = event.get("y")
            if not isinstance(event_x, int) or not isinstance(event_y, int):
                event_statistics["invalid_sprites"].append(
                    {**event_identity, "message": "event has no integer position"}
                )
                continue
            destination_x = event_x * TILE_SIZE + TILE_SIZE // 2 - CHARACTER_FRAME_WIDTH // 2
            destination_y = event_y * TILE_SIZE + TILE_SIZE - CHARACTER_FRAME_HEIGHT
            canvas.blit(
                charset,
                source_x,
                source_y,
                CHARACTER_FRAME_WIDTH,
                CHARACTER_FRAME_HEIGHT,
                destination_x,
                destination_y,
            )
            canvas.fill_rect(
                event_x * TILE_SIZE + TILE_SIZE // 2 - 1,
                event_y * TILE_SIZE + TILE_SIZE - 3,
                2,
                2,
                (255, 224, 92, 255),
            )
            event_statistics["sprites_drawn"] += 1

    picture_statistics = {
        "enabled": show_lightmap,
        "selector": "ShowPicture names containing 'lightmap'",
        "reference_screen": {
            "width": PICTURE_SCREEN_WIDTH,
            "height": PICTURE_SCREEN_HEIGHT,
        },
        "commands_found": 0,
        "pictures_drawn": 0,
        "drawn_pictures": [],
        "missing_pictures": [],
        "ambiguous_pictures": [],
        "invalid_pictures": [],
        "skipped_pictures": [],
    }
    if show_lightmap:
        for picture_command in _picture_commands(event_page_selections):
            command = picture_command["command"]
            picture_name = command.get("string")
            if not _lightmap_name(picture_name):
                continue
            picture_statistics["commands_found"] += 1
            identity = {
                "picture_id": None,
                "picture_name": picture_name,
                "event_id": picture_command.get("event_id"),
                "event_name": picture_command.get("event_name"),
                "page_index": picture_command.get("page_index"),
                "command_index": picture_command.get("command_index"),
            }
            picture = _parse_show_picture(command)
            if picture is None:
                picture_statistics["skipped_pictures"].append(
                    {**identity, "reason": "ShowPicture has fewer than 14 integer parameters"}
                )
                continue
            identity["picture_id"] = picture["picture_id"]
            identity.update(
                {
                    "position": [picture["x"], picture["y"]],
                    "fixed_to_map": picture["fixed_to_map"],
                    "zoom": picture["zoom"],
                    "top_transparency": picture["top_transparency"],
                    "use_transparent_color": picture["use_transparent_color"],
                }
            )
            if picture["position_mode"] != 0:
                picture_statistics["skipped_pictures"].append(
                    {**identity, "reason": "variable picture coordinates are not evaluated"}
                )
                continue
            picture_path, picture_descriptor, picture_matches = _resolve_asset(
                indexes,
                "picture",
                picture_name,
            )
            if picture_path is None or picture_descriptor is None:
                picture_statistics["missing_pictures"].append(identity)
                continue
            if picture_matches > 1:
                picture_statistics["ambiguous_pictures"].append(identity)
            try:
                picture_image = read_png(
                    picture_path,
                    transparent_index_zero=picture["use_transparent_color"],
                )
            except (OSError, PngError) as error:
                picture_statistics["invalid_pictures"].append(
                    {**identity, "message": str(error)}
                )
                continue
            if picture["zoom"] == 0:
                picture_statistics["skipped_pictures"].append(
                    {**identity, "reason": "picture zoom is zero"}
                )
                continue
            if picture["zoom"] != 100:
                picture_image = picture_image.resize_nearest(
                    max(1, picture_image.width * picture["zoom"] // 100),
                    max(1, picture_image.height * picture["zoom"] // 100),
                )
            opacity = 255 * (100 - picture["top_transparency"]) // 100
            picture_image = picture_image.with_opacity(opacity)
            destination_x = picture["x"] - picture_image.width // 2
            destination_y = picture["y"] - picture_image.height // 2
            canvas.blit(
                picture_image,
                0,
                0,
                picture_image.width,
                picture_image.height,
                destination_x,
                destination_y,
            )
            picture_statistics["pictures_drawn"] += 1
            picture_statistics["drawn_pictures"].append(
                {
                    **identity,
                    "source": {
                        "root": picture_descriptor["root"],
                        "path": picture_descriptor["path"],
                    },
                }
            )

    tile_statistics["by_block"] = dict(sorted(tile_statistics["by_block"].items()))
    tile_statistics["unsupported_tile_ids"] = sorted(tile_statistics["unsupported_tile_ids"])[:100]
    output_image = canvas.scale_nearest(scale)
    manifest = {
        "schema_version": 1,
        "renderer": {
            "name": "darkest-journey-static-map-renderer",
            "version": "0.1.0",
            "read_only": True,
            "tile_size": TILE_SIZE,
            "scale": scale,
            "autotile_animation_frame": 0,
        },
        "source": {
            "project": str(project_path),
            "map": map_report["file"],
            "map_filename": map_filename,
            "chipset": {
                "id": chipset_id,
                "name": chipset_name,
                "database_name": chipset_record.get("name"),
                "mode": chipset_mode,
                "root": chipset_descriptor["root"],
                "path": chipset_descriptor["path"],
            },
        },
        "output": {
            "width": output_image.width,
            "height": output_image.height,
            "base_width": canvas.width,
            "base_height": canvas.height,
        },
        "map": {
            "width": width,
            "height": height,
            "dimensions_defaults_used": dimensions.get("defaults_used", []),
            "field_defaults_used": map_data.get("field_defaults_used", []),
        },
        "event_state": {
            "semantics": "RPG Maker 2003 event page snapshot",
            "defaults": {
                "switch": False,
                "variable": 0,
            },
            "switches": [
                {"id": switch_id, "value": value}
                for switch_id, value in preview_state.switches.items()
            ],
            "variables": [
                {"id": variable_id, "value": value}
                for variable_id, value in preview_state.variables.items()
            ],
        },
        "tiles": tile_statistics,
        "events": event_statistics,
        "pictures": picture_statistics,
        "limitations": [
            "runtime tile substitutions are not applied",
            "autotiles use animation frame 0",
            "event page selection uses an explicit preview state rather than a live save",
            "item, actor, timer, and unknown event page conditions are not evaluated",
            "passability-based event z-order is not evaluated",
            "lightmap selection does not execute picture replacement order",
            "picture tones, effects, and variable coordinates are not evaluated",
        ],
    }
    return output_image, manifest
