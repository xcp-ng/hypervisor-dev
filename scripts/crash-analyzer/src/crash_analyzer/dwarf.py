"""DWARF-backed Xen type and structure layout inspection."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from elftools.common.exceptions import ELFError  # type: ignore[import-untyped]
from elftools.elf.elffile import ELFFile  # type: ignore[import-untyped]

from .errors import CrashAnalyzerError
from .renderers import MemberSelector, SpinlockRenderer, TypeRenderer, VmBranchSelector

_STRUCTURE_TAGS = {"DW_TAG_structure_type", "DW_TAG_union_type"}
_QUALIFIER_TAGS = {
    "DW_TAG_const_type",
    "DW_TAG_volatile_type",
    "DW_TAG_restrict_type",
    "DW_TAG_atomic_type",
}
_SIGNED_ENCODINGS = {5, 6}  # DW_ATE_signed, DW_ATE_signed_char
_CHAR_ENCODINGS = {6, 8}  # DW_ATE_signed_char, DW_ATE_unsigned_char
# These are the only Xen public domctl flags interpreted here.  Other flags
# must not be inferred from their ordering.
_XEN_DOMCTL_CDF_hvm: Final = 0
XEN_DOMCTL_CDF_hvm: Final = 1 << _XEN_DOMCTL_CDF_hvm
_XEN_DOMCTL_CDF_nested_virt: Final = 6
XEN_DOMCTL_CDF_nested_virt: Final = 1 << _XEN_DOMCTL_CDF_nested_virt


def _attribute(die: Any, name: str) -> Any | None:
    attribute = die.attributes.get(name)
    return None if attribute is None else attribute.value


def _name(die: Any) -> str | None:
    value = _attribute(die, "DW_AT_name")
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else None


@dataclass(frozen=True)
class Member:
    """A direct member of a structure or union."""

    name: str
    type_die: Any | None
    offset: int | None
    size: int | None
    bit_size: int | None = None
    bit_offset: int | None = None


@dataclass(frozen=True)
class ObservedValue:
    """A leaf value whose containing range overlaps captured dump bytes."""

    path: str
    type_die: Any | None
    offset: int
    size: int | None
    value: str | None


@dataclass(frozen=True)
class TypeContext:
    """Runtime variant information used while expanding anonymous unions."""

    vm_type: Literal["pv", "hvm"] | None = None
    nested_virt: bool | None = None


class SymbolFile:
    """Read named types and member layouts from an ELF/DWARF Xen symbol file."""

    def __init__(
        self,
        path: Path,
        renderers: Iterable[TypeRenderer] | None = None,
        selectors: Iterable[MemberSelector] | None = None,
    ):
        self.path = path
        self._stream = None
        try:
            self._stream = path.open("rb")
            self._elf = ELFFile(self._stream)
        except (OSError, ELFError, ValueError) as exc:
            if self._stream is not None:
                self._stream.close()
            raise CrashAnalyzerError(f"cannot read symbol file {path}: {exc}") from exc

        if not self._elf.has_dwarf_info():
            self.close()
            raise CrashAnalyzerError(f"symbol file {path} does not contain DWARF debug information")

        self.dwarf = self._elf.get_dwarf_info()
        self.pointer_size = self._elf.elfclass // 8
        self.byteorder: Literal["little", "big"] = "little" if self._elf.little_endian else "big"
        self._renderers = [*(renderers or ()), SpinlockRenderer()]
        self._selectors = [*(selectors or ()), VmBranchSelector()]
        self._named: dict[str, list[Any]] = {}
        self._index_types()

    def __enter__(self) -> SymbolFile:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the symbol file if it is open."""

        stream = getattr(self, "_stream", None)
        if stream is not None and not stream.closed:
            stream.close()

    def _index_types(self) -> None:
        for compilation_unit in self.dwarf.iter_CUs():
            interesting_tags = _STRUCTURE_TAGS | {
                "DW_TAG_typedef",
                "DW_TAG_base_type",
                "DW_TAG_enumeration_type",
            }
            for die in compilation_unit.iter_DIEs():
                if die.tag not in interesting_tags:
                    continue
                die_name = _name(die)
                if die_name:
                    self._named.setdefault(die_name, []).append(die)

    @staticmethod
    def _normalise_name(type_name: str) -> tuple[str, str | None]:
        name = " ".join(type_name.strip().split())
        for tag in ("struct", "union", "enum"):
            prefix = f"{tag} "
            if name.startswith(prefix):
                return name[len(prefix) :], tag
        return name, None

    def find(self, type_name: str) -> Any:
        """Find the best matching named DIE for a source-level type name."""

        name, requested_tag = self._normalise_name(type_name)
        candidates = self._named.get(name, [])
        if requested_tag:
            expected = (
                f"DW_TAG_{requested_tag}ure_type"
                if requested_tag == "struct"
                else f"DW_TAG_{requested_tag}_type"
            )
            candidates = [die for die in candidates if die.tag == expected]
        if not candidates:
            raise CrashAnalyzerError(f"type {type_name!r} was not found in {self.path}")

        # Forward declarations are useful to the compiler but not for layout
        # inspection. Prefer a complete DIE and then the candidate with the most
        # information if a binary contains repeated type declarations.
        complete = [die for die in candidates if _attribute(die, "DW_AT_byte_size") is not None]
        return max(complete or candidates, key=lambda die: len(list(die.iter_children())))

    @staticmethod
    def _underlying(type_die: Any | None) -> Any | None:
        current = type_die
        while current is not None and (
            current.tag == "DW_TAG_typedef" or current.tag in _QUALIFIER_TAGS
        ):
            attribute = current.attributes.get("DW_AT_type")
            if attribute is None:
                break
            current = current.get_DIE_from_attribute("DW_AT_type")
        return current

    def _type_die(self, die: Any) -> Any | None:
        attribute = die.attributes.get("DW_AT_type")
        return None if attribute is None else die.get_DIE_from_attribute("DW_AT_type")

    def _size(self, type_die: Any | None) -> int | None:
        if type_die is None:
            return None
        size = _attribute(type_die, "DW_AT_byte_size")
        if isinstance(size, int):
            return size
        if type_die.tag == "DW_TAG_pointer_type":
            return self.pointer_size
        return self._size(self._type_die(type_die))

    def register_renderer(self, renderer: TypeRenderer) -> None:
        """Register a type renderer, giving it precedence over built-ins."""

        self._renderers.insert(0, renderer)

    def renderer_for(self, type_die: Any | None) -> TypeRenderer | None:
        """Return the first renderer that recognizes ``type_die``."""

        return next(
            (renderer for renderer in self._renderers if renderer.matches(self, type_die)),
            None,
        )

    def render_value(self, type_die: Any | None, data: bytes) -> str | None:
        """Render a complete value with a registered semantic renderer."""

        renderer = self.renderer_for(type_die)
        return None if renderer is None else renderer.render(self, type_die, data)

    def select_members(
        self,
        type_die: Any | None,
        members: Iterable[Any],
        context: TypeContext,
    ) -> list[Any]:
        """Apply the first registered context-sensitive member selector."""

        members = list(members)
        for selector in self._selectors:
            selected = selector.select(self, type_die, members, context)
            if selected is not None:
                return list(selected)
        return members

    def register_selector(self, selector: MemberSelector) -> None:
        """Register a member selector, giving it precedence over built-ins."""

        self._selectors.insert(0, selector)

    def _alignment(self, type_die: Any | None) -> int | None:
        underlying = self._underlying(type_die)
        alignment = _attribute(underlying, "DW_AT_alignment") if underlying is not None else None
        return alignment if isinstance(alignment, int) else None

    def structure(self, type_name: str) -> Structure:
        """Return the layout for a structure or union named by the user."""

        named_die = self.find(type_name)
        structure_die = self._underlying(named_die)
        if structure_die is None or structure_die.tag not in _STRUCTURE_TAGS:
            raise CrashAnalyzerError(f"type {type_name!r} is not a structure or union")
        members: list[Member] = []
        for child in structure_die.iter_children():
            if child.tag != "DW_TAG_member":
                continue
            location = _attribute(child, "DW_AT_data_member_location")
            offset = (
                location
                if isinstance(location, int)
                else (0 if structure_die.tag == "DW_TAG_union_type" else None)
            )
            member_type = self._type_die(child)
            members.append(
                Member(
                    name=_name(child) or "<anonymous>",
                    type_die=member_type,
                    offset=offset,
                    size=self._size(member_type),
                    bit_size=_attribute(child, "DW_AT_bit_size"),
                    bit_offset=_attribute(child, "DW_AT_bit_offset"),
                )
            )
        return Structure(
            name=_name(structure_die) or type_name,
            requested_name=type_name,
            kind="struct" if structure_die.tag == "DW_TAG_structure_type" else "union",
            size=self._size(structure_die),
            alignment=self._alignment(structure_die),
            members=members,
            symbols=self,
        )

    def type_name(self, type_die: Any | None) -> str:
        """Render a DWARF type in a compact C-like form."""

        if type_die is None:
            return "<unknown>"
        tag = type_die.tag
        if tag == "DW_TAG_pointer_type":
            return f"{self.type_name(self._type_die(type_die))} *"
        if tag == "DW_TAG_array_type":
            element = self.type_name(self._type_die(type_die))
            bounds: list[str] = []
            for child in type_die.iter_children():
                upper = _attribute(child, "DW_AT_upper_bound")
                bounds.append(str(upper + 1) if isinstance(upper, int) else "?")
            return f"{element}[{']['.join(bounds)}]"
        if tag == "DW_TAG_typedef":
            return _name(type_die) or self.type_name(self._type_die(type_die))
        if tag in _QUALIFIER_TAGS:
            qualifier = tag.removeprefix("DW_TAG_").removesuffix("_type")
            return f"{qualifier} {self.type_name(self._type_die(type_die))}"
        if tag == "DW_TAG_structure_type":
            return f"struct {_name(type_die) or '<anonymous>'}"
        if tag == "DW_TAG_union_type":
            return f"union {_name(type_die) or '<anonymous>'}"
        if tag == "DW_TAG_enumeration_type":
            return f"enum {_name(type_die) or '<anonymous>'}"
        return _name(type_die) or tag.removeprefix("DW_TAG_")

    def decode(self, type_die: Any | None, data: bytes) -> str:
        """Decode a captured scalar value using its DWARF type."""

        if type_die is None:
            return f"0x{int.from_bytes(data, self.byteorder):x}"
        if type_die.tag == "DW_TAG_typedef" or type_die.tag in _QUALIFIER_TAGS:
            return self.decode(self._type_die(type_die), data)
        if type_die.tag == "DW_TAG_pointer_type":
            value = int.from_bytes(data, self.byteorder)
            return "NULL" if value == 0 else f"0x{value:0{self.pointer_size * 2}x}"
        if type_die.tag == "DW_TAG_enumeration_type":
            value = int.from_bytes(data, self.byteorder, signed=False)
            names = {
                _attribute(child, "DW_AT_const_value"): _name(child)
                for child in type_die.iter_children()
                if child.tag == "DW_TAG_enumerator"
            }
            return f"{names[value]} ({value})" if value in names else str(value)
        if type_die.tag == "DW_TAG_base_type":
            size = _attribute(type_die, "DW_AT_byte_size") or len(data)
            data = data[:size]
            encoding = _attribute(type_die, "DW_AT_encoding")
            if encoding in _CHAR_ENCODINGS and len(data) == 1:
                value = int.from_bytes(data, self.byteorder)
                return repr(chr(value)) if 32 <= value < 127 else str(value)
            signed = encoding in _SIGNED_ENCODINGS
            return str(int.from_bytes(data, self.byteorder, signed=signed))
        if type_die.tag == "DW_TAG_array_type":
            return f"<{self.type_name(type_die)}: {len(data)} bytes>"
        if type_die.tag in _STRUCTURE_TAGS:
            return f"<{self.type_name(type_die)}: {len(data)} bytes>"
        return f"0x{int.from_bytes(data, self.byteorder):x}"

    def _extract_bits(self, data: bytes, bit_size: int, bit_offset: int) -> int:
        value = int.from_bytes(data, self.byteorder)
        total_bits = len(data) * 8
        shift = total_bits - bit_offset - bit_size if self.byteorder == "little" else bit_offset
        return (value >> shift) & ((1 << bit_size) - 1)

    def decode_member(
        self,
        type_die: Any | None,
        data: bytes,
        bit_size: int | None = None,
        bit_offset: int | None = None,
    ) -> str:
        """Decode a member, including DWARF-described bitfields."""

        if bit_size is not None and bit_offset is not None:
            return str(self._extract_bits(data, bit_size, bit_offset))
        return self.decode(type_die, data)


@dataclass(frozen=True)
class Structure:
    """A resolved structure layout."""

    name: str
    requested_name: str
    kind: str
    size: int | None
    alignment: int | None
    members: list[Member]
    symbols: SymbolFile

    def vm_type(self, data: dict[int, int]) -> Literal["pv", "hvm"] | None:
        """Resolve a domain's active PV/HVM branch from ``domain.options``."""

        if self.name != "domain":
            return None
        options_member = next((member for member in self.members if member.name == "options"), None)
        if options_member is None or options_member.offset is None or options_member.size is None:
            return None
        values = [data.get(options_member.offset + index) for index in range(options_member.size)]
        if any(value is None for value in values):
            return None
        options = int.from_bytes(
            bytes(value for value in values if value is not None), self.symbols.byteorder
        )
        return "hvm" if options & XEN_DOMCTL_CDF_hvm else "pv"

    def context(self, data: dict[int, int]) -> TypeContext:
        """Resolve the domain's variant flags from its captured ``options``."""

        if self.name != "domain":
            return TypeContext()
        options_member = next((member for member in self.members if member.name == "options"), None)
        if options_member is None or options_member.offset is None or options_member.size is None:
            return TypeContext()
        values = [data.get(options_member.offset + index) for index in range(options_member.size)]
        if any(value is None for value in values):
            return TypeContext()
        options = int.from_bytes(
            bytes(value for value in values if value is not None), self.symbols.byteorder
        )
        return TypeContext(
            vm_type="hvm" if options & XEN_DOMCTL_CDF_hvm else "pv",
            nested_virt=bool(options & XEN_DOMCTL_CDF_nested_virt),
        )

    def value_for(self, member: Member, data: dict[int, int]) -> str | None:
        """Decode a member if all its bytes were captured."""

        if member.offset is None or member.size is None:
            return None
        values = [data.get(member.offset + index) for index in range(member.size)]
        if any(value is None for value in values):
            return None
        raw = bytes(value for value in values if value is not None)
        rendered = self.symbols.render_value(member.type_die, raw)
        if rendered is not None:
            return rendered
        return self.symbols.decode_member(member.type_die, raw, member.bit_size, member.bit_offset)

    @staticmethod
    def _overlaps(data: dict[int, int], offset: int, size: int | None) -> bool:
        return size is not None and any(offset <= position < offset + size for position in data)

    @staticmethod
    def _value(data: dict[int, int], offset: int, size: int | None) -> bytes | None:
        if size is None:
            return None
        values = [data.get(offset + index) for index in range(size)]
        if any(value is None for value in values):
            return None
        return bytes(value for value in values if value is not None)

    def _observed_type(
        self,
        type_die: Any | None,
        offset: int,
        path: str,
        data: dict[int, int],
        depth: int = 0,
        bit_size: int | None = None,
        bit_offset: int | None = None,
        context: TypeContext | None = None,
    ) -> list[ObservedValue]:
        if depth > 16:
            return []
        size = self.symbols._size(type_die)
        underlying = self.symbols._underlying(type_die)
        if underlying is None or not self._overlaps(data, offset, size):
            return []

        renderer = self.symbols.renderer_for(type_die)
        if renderer is not None:
            raw = self._value(data, offset, size)
            return [
                ObservedValue(
                    path=path,
                    type_die=type_die,
                    offset=offset,
                    size=size,
                    value=renderer.render(self.symbols, type_die, raw) if raw is not None else None,
                )
            ]

        if underlying.tag in _STRUCTURE_TAGS:
            values: list[ObservedValue] = []
            children = [
                child for child in underlying.iter_children() if child.tag == "DW_TAG_member"
            ]
            children = self.symbols.select_members(type_die, children, context or TypeContext())
            for child in children:
                child_type = self.symbols._type_die(child)
                child_offset = _attribute(child, "DW_AT_data_member_location")
                if not isinstance(child_offset, int):
                    child_offset = 0 if underlying.tag == "DW_TAG_union_type" else None
                if child_offset is None:
                    continue
                child_name = _name(child) or "<anonymous>"
                values.extend(
                    self._observed_type(
                        child_type,
                        offset + child_offset,
                        f"{path}.{child_name}",
                        data,
                        depth + 1,
                        _attribute(child, "DW_AT_bit_size"),
                        _attribute(child, "DW_AT_bit_offset"),
                        context,
                    )
                )
            if values:
                return values
            raw = self._value(data, offset, size)
            return [
                ObservedValue(
                    path=path,
                    type_die=type_die,
                    offset=offset,
                    size=size,
                    value=self.symbols.decode(type_die, raw) if raw is not None else None,
                )
            ]

        if underlying.tag == "DW_TAG_array_type":
            element_type = self.symbols._type_die(underlying)
            element_size = self.symbols._size(element_type)
            subranges = list(underlying.iter_children())
            upper = _attribute(subranges[0], "DW_AT_upper_bound") if subranges else None
            count = upper + 1 if isinstance(upper, int) else None
            element_underlying = self.symbols._underlying(element_type)
            if (
                count is None
                or element_size is None
                or element_underlying is None
                or element_underlying.tag not in _STRUCTURE_TAGS | {"DW_TAG_array_type"}
            ):
                raw = self._value(data, offset, size)
                return [
                    ObservedValue(
                        path=path,
                        type_die=type_die,
                        offset=offset,
                        size=size,
                        value=self.symbols.decode(type_die, raw) if raw is not None else None,
                    )
                ]
            values = []
            for index in range(count):
                values.extend(
                    self._observed_type(
                        element_type,
                        offset + index * element_size,
                        f"{path}[{index}]",
                        data,
                        depth + 1,
                        context=context,
                    )
                )
            return values

        raw = self._value(data, offset, size)
        return [
            ObservedValue(
                path=path,
                type_die=type_die,
                offset=offset,
                size=size,
                value=(
                    self.symbols.decode_member(type_die, raw, bit_size, bit_offset)
                    if raw is not None
                    else None
                ),
            )
        ]

    def observed_values(
        self, data: dict[int, int], context: TypeContext | None = None
    ) -> list[ObservedValue]:
        """Expand captured bytes into sparse leaf values using the type layout."""

        values: list[ObservedValue] = []
        if context is None:
            context = self.context(data)
        elif context.vm_type is None:
            detected = self.context(data)
            context = TypeContext(vm_type=detected.vm_type, nested_virt=context.nested_virt)
        for member in self.members:
            if member.offset is not None:
                values.extend(
                    self._observed_type(
                        member.type_die,
                        member.offset,
                        member.name,
                        data,
                        context=context,
                    )
                )
        return values
