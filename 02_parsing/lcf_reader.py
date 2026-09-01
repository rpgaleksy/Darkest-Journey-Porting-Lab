"""Small, dependency-free primitives for reading RPG Maker LCF files.

The reader deliberately has no writer or mutation API.  It is intended as a
safe first layer for inspecting RPG Maker 2000/2003 data on systems where the
original Windows runtime is unavailable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterator, Optional


class LcfParseError(ValueError):
    """Raised when an LCF stream is truncated or structurally invalid."""


@dataclass(frozen=True)
class LcfChunk:
    """One length-prefixed LCF chunk."""

    chunk_id: int
    offset: int
    payload_offset: int
    length: int
    payload: bytes

    @property
    def end_offset(self) -> int:
        return self.payload_offset + self.length

    def descriptor(self, preview_bytes: int = 48) -> dict:
        """Return a compact, JSON-friendly description without large payloads."""

        preview = self.payload[:preview_bytes]
        return {
            "id": self.chunk_id,
            "offset": self.offset,
            "payload_offset": self.payload_offset,
            "length": self.length,
            "payload_preview_hex": preview.hex(" "),
            "payload_sha256": hashlib.sha256(self.payload).hexdigest(),
        }


@dataclass(frozen=True)
class StructRead:
    """Result of reading a zero-terminated sequence of LCF chunks."""

    chunks: tuple[LcfChunk, ...]
    terminated: bool
    terminator_offset: Optional[int]
    end_offset: int
    remaining: int


class LcfReader:
    """Bounds-checked reader for the primitive LCF encodings.

    LCF uses a base-128 integer encoding for IDs, lengths and most scalar
    values.  RPG Maker's fixed-width numeric values are stored little-endian
    on disk; the explicit byte order keeps parsing independent of host CPU.
    """

    def __init__(
        self,
        data: bytes,
        *,
        source_name: str = "<memory>",
        base_offset: int = 0,
    ) -> None:
        self._data = bytes(data)
        self.source_name = source_name
        self.base_offset = base_offset
        self._position = 0

    @property
    def position(self) -> int:
        """Absolute position in the original source stream."""

        return self.base_offset + self._position

    @property
    def relative_position(self) -> int:
        return self._position

    @property
    def remaining(self) -> int:
        return len(self._data) - self._position

    @property
    def eof(self) -> bool:
        return self._position >= len(self._data)

    def _require(self, count: int) -> None:
        if count < 0:
            raise ValueError("count must not be negative")
        if self._position + count > len(self._data):
            raise LcfParseError(
                f"{self.source_name}: truncated read at offset {self.position}; "
                f"needed {count} byte(s), only {self.remaining} remaining"
            )

    def read_bytes(self, count: int) -> bytes:
        self._require(count)
        start = self._position
        self._position += count
        return self._data[start:self._position]

    def peek_bytes(self, count: int) -> bytes:
        self._require(count)
        return self._data[self._position:self._position + count]

    def read_u8(self) -> int:
        return self.read_bytes(1)[0]

    def read_compressed_int(self, *, max_bytes: int = 5) -> int:
        """Read the LCF base-128, big-endian integer representation."""

        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")

        start = self.position
        value = 0
        for _ in range(max_bytes):
            byte = self.read_u8()
            value = (value << 7) | (byte & 0x7F)
            if not byte & 0x80:
                return value

        raise LcfParseError(
            f"{self.source_name}: compressed integer at offset {start} "
            f"uses more than {max_bytes} byte(s)"
        )

    def read_fixed_int16(self) -> int:
        return int.from_bytes(self.read_bytes(2), "little", signed=True)

    def read_fixed_uint16(self) -> int:
        return int.from_bytes(self.read_bytes(2), "little", signed=False)

    def read_fixed_uint32(self) -> int:
        return int.from_bytes(self.read_bytes(4), "little", signed=False)

    def read_string(self, length: int, *, encoding: str = "cp1252") -> str:
        raw = self.read_bytes(length)
        return raw.decode(encoding, errors="replace")

    def read_header(
        self,
        *,
        expected: Optional[str] = None,
        encoding: str = "ascii",
    ) -> dict:
        length_offset = self.position
        length = self.read_compressed_int()
        raw_offset = self.position
        raw = self.read_bytes(length)
        value = raw.decode(encoding, errors="replace")
        if expected is not None and value != expected:
            raise LcfParseError(
                f"{self.source_name}: expected header {expected!r} at "
                f"offset {raw_offset}, got {value!r}"
            )
        return {
            "offset": length_offset,
            "length": length,
            "value": value,
            "raw_hex": raw.hex(" "),
        }

    def read_chunk(self) -> Optional[LcfChunk]:
        """Read one chunk, returning None for a zero terminator or EOF."""

        if self.eof:
            return None

        offset = self.position
        chunk_id = self.read_compressed_int()
        if chunk_id == 0:
            return None

        length = self.read_compressed_int()
        payload_offset = self.position
        payload = self.read_bytes(length)
        return LcfChunk(
            chunk_id=chunk_id,
            offset=offset,
            payload_offset=payload_offset,
            length=length,
            payload=payload,
        )

    def iter_chunks(self) -> Iterator[LcfChunk]:
        while not self.eof:
            chunk = self.read_chunk()
            if chunk is None:
                return
            yield chunk

    def subreader(self, chunk: LcfChunk) -> "LcfReader":
        return LcfReader(
            chunk.payload,
            source_name=self.source_name,
            base_offset=chunk.payload_offset,
        )


def read_struct_chunks(reader: LcfReader) -> StructRead:
    """Read a struct's chunks and consume its zero terminator if present."""

    chunks = []
    while not reader.eof:
        marker_offset = reader.position
        chunk = reader.read_chunk()
        if chunk is None:
            terminated = reader.position > marker_offset
            return StructRead(
                chunks=tuple(chunks),
                terminated=terminated,
                terminator_offset=marker_offset if terminated else None,
                end_offset=reader.position,
                remaining=reader.remaining,
            )
        chunks.append(chunk)

    return StructRead(
        chunks=tuple(chunks),
        terminated=False,
        terminator_offset=None,
        end_offset=reader.position,
        remaining=reader.remaining,
    )
