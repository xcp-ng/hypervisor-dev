"""Semantic renderers for Xen types whose raw fields are hard to read."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

if TYPE_CHECKING:
    from .dwarf import SymbolFile


class TypeRenderer(Protocol):
    """Render a complete DWARF value using type-specific semantics."""

    def matches(self, symbols: SymbolFile, type_die: Any | None) -> bool:
        """Return whether this renderer owns ``type_die``."""
        ...

    def render(self, symbols: SymbolFile, type_die: Any | None, data: bytes) -> str:
        """Render the captured bytes as a human-readable value."""
        ...


class SelectorContext(Protocol):
    """Context attributes needed by member selectors."""

    vm_type: Literal["pv", "hvm"] | None
    nested_virt: bool | None


class MemberSelector(Protocol):
    """Select the members to expand for a composite DWARF value."""

    def select(
        self,
        symbols: SymbolFile,
        type_die: Any | None,
        members: Iterable[Any],
        context: SelectorContext,
    ) -> Iterable[Any] | None:
        """Return selected members, or ``None`` when this selector does not apply."""


class SpinlockRenderer:
    """Render Xen ``spinlock_t`` values as lock state and ownership."""

    def matches(self, symbols: SymbolFile, type_die: Any | None) -> bool:
        underlying = symbols._underlying(type_die)
        return underlying is not None and _name(underlying) == "spinlock"

    def render(self, symbols: SymbolFile, type_die: Any | None, data: bytes) -> str:
        lock_type = symbols._underlying(type_die)
        assert lock_type is not None
        members = {
            _name(child): child
            for child in lock_type.iter_children()
            if child.tag == "DW_TAG_member" and _name(child)
        }
        tickets_member = members.get("tickets")
        recurse_cpu_member = members.get("recurse_cpu")
        recurse_count_member = members.get("recurse_cnt")
        if tickets_member is None or recurse_cpu_member is None or recurse_count_member is None:
            return f"state unavailable ({symbols.type_name(type_die)}, {len(data)} bytes captured)"

        def member_bytes(member: Any) -> bytes | None:
            offset = _attribute(member, "DW_AT_data_member_location")
            member_size = symbols._size(symbols._type_die(member))
            if not isinstance(offset, int) or member_size is None:
                return None
            value = data[offset : offset + member_size]
            return value if len(value) == member_size else None

        cpu_bits = cast(int, _attribute(recurse_cpu_member, "DW_AT_bit_size"))
        count_bits = cast(int, _attribute(recurse_count_member, "DW_AT_bit_size"))
        cpu_offset = cast(int, _attribute(recurse_cpu_member, "DW_AT_bit_offset"))
        count_offset = cast(int, _attribute(recurse_count_member, "DW_AT_bit_offset"))
        if not all(
            isinstance(value, int) for value in (cpu_bits, count_bits, cpu_offset, count_offset)
        ):
            return f"state unavailable ({symbols.type_name(type_die)}, bitfield metadata missing)"

        tickets = member_bytes(tickets_member)
        recurse_cpu_storage = member_bytes(recurse_cpu_member)
        recurse_count_storage = member_bytes(recurse_count_member)
        if tickets is None or recurse_cpu_storage is None or recurse_count_storage is None:
            return f"state unavailable ({symbols.type_name(type_die)}, member bytes missing)"

        recurse_cpu = symbols._extract_bits(recurse_cpu_storage, cpu_bits, cpu_offset)
        recurse_count = symbols._extract_bits(recurse_count_storage, count_bits, count_offset)
        head = int.from_bytes(tickets[0:2], symbols.byteorder)
        tail = int.from_bytes(tickets[2:4], symbols.byteorder)
        no_cpu = (1 << cpu_bits) - 1
        held = head != tail or recurse_cpu != no_cpu
        state = "HELD" if held else "FREE"
        owner = "none" if recurse_cpu == no_cpu else f"CPU {recurse_cpu}"
        details = (
            f"{state} (tickets head={head}, tail={tail}; "
            f"recursive owner={owner}; depth={recurse_count}"
        )
        if not held and recurse_count:
            details += "; inconsistent: non-zero depth while unlocked"
        return f"{details})"


class VmBranchSelector:
    """Select the active ``pv`` or ``hvm`` branch of an anonymous union."""

    def select(
        self,
        symbols: SymbolFile,
        type_die: Any | None,
        members: Iterable[Any],
        context: SelectorContext,
    ) -> Iterable[Any] | None:
        members = list(members)
        member_names = {_name(member) for member in members}
        if {"pv", "hvm"} <= member_names:
            active = context.vm_type
            if active is None:
                return None
            return [member for member in members if _name(member) == active]

        if {"vmx", "svm"} <= member_names:
            return None
        if {"nvmx", "nsvm"} <= member_names and context.nested_virt is False:
            return []
        return None


def _attribute(die: Any, name: str) -> Any | None:
    attribute = die.attributes.get(name)
    return None if attribute is None else attribute.value


def _name(die: Any) -> str | None:
    value = _attribute(die, "DW_AT_name")
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else None
