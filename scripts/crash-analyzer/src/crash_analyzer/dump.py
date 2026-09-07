"""Parser for the sparse structure dump format used by the Xen diagnostics."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from .errors import CrashAnalyzerError

_HEADER = re.compile(
    r"^(?P<type>(?:(?:struct|union|enum)\s+)?[A-Za-z_][A-Za-z0-9_]*)"
    r"\s+\((?P<address>0x[0-9a-fA-F]+)\)"
    r"(?:\s+for\s+vcpu\s+(?P<vcpu>[0-9]+))?\s*$"
)
_OFFSET = re.compile(r"^(?P<offset>[0-9a-fA-F]+):\s+(?P<body>.*)$")
_BYTE = re.compile(r"^[0-9a-fA-F]{2}$")


@dataclass(frozen=True)
class DumpRow:
    """One row of bytes in a structure dump."""

    offset: int
    data: bytes


@dataclass
class StructureDump:
    """The bytes captured for one structure instance."""

    declared_type: str
    address: int
    vcpu: int | None = None
    rows: list[DumpRow] = field(default_factory=list)

    @property
    def bytes(self) -> dict[int, int]:
        """Return the captured bytes indexed by their structure-relative offset."""

        result: dict[int, int] = {}
        for row in self.rows:
            result.update({row.offset + index: value for index, value in enumerate(row.data)})
        return result

    @property
    def observed_offsets(self) -> set[int]:
        """Return all structure-relative offsets present in the abridged dump."""

        return set(self.bytes)

    def read(self, offset: int, size: int) -> bytes | None:
        """Read a range when every byte in it was present in the dump."""

        data = self.bytes
        values = [data.get(offset + index) for index in range(size)]
        if any(value is None for value in values):
            return None
        return bytes(value for value in values if value is not None)


def parse_dump(source: TextIO | Iterable[str]) -> list[StructureDump]:
    """Parse a structure dump from a text stream or iterable of lines.

    The format intentionally permits omitted regions represented by ``...``. Those
    regions are not synthesized: callers can distinguish an unavailable value from
    a value consisting of zero bytes.
    """

    dumps: list[StructureDump] = []
    current: StructureDump | None = None
    for line_number, raw_line in enumerate(source, 1):
        line = raw_line.strip()
        if not line or line == "...":
            continue

        header = _HEADER.fullmatch(line)
        if header:
            current = StructureDump(
                declared_type=header.group("type"),
                address=int(header.group("address"), 16),
                vcpu=int(header.group("vcpu")) if header.group("vcpu") else None,
            )
            dumps.append(current)
            continue

        row_match = _OFFSET.fullmatch(line)
        if row_match:
            if current is None:
                raise CrashAnalyzerError(
                    f"line {line_number}: found bytes before a structure header"
                )
            tokens = row_match.group("body").split()
            byte_tokens: list[str] = []
            for token in tokens:
                if not _BYTE.fullmatch(token):
                    break
                byte_tokens.append(token)
            if not byte_tokens:
                raise CrashAnalyzerError(f"line {line_number}: no byte values found")
            current.rows.append(
                DumpRow(
                    offset=int(row_match.group("offset"), 16),
                    data=bytes.fromhex(" ".join(byte_tokens)),
                )
            )
            continue

        # The first line is commonly a human-readable title. Unknown lines are
        # ignored so a dump can acquire annotations without breaking parsing.

    return dumps


def load_dump(path: Path) -> list[StructureDump]:
    """Load and parse a dump file."""

    try:
        with path.open(encoding="utf-8") as stream:
            return parse_dump(stream)
    except OSError as exc:
        raise CrashAnalyzerError(f"cannot read dump {path}: {exc}") from exc
