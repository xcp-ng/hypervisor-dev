"""Command-line interface for the Xen structure dump explorer."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, cast

from .dump import StructureDump, load_dump
from .dwarf import Member, ObservedValue, Structure, SymbolFile, TypeContext
from .errors import CrashAnalyzerError


def _layout_dict(layout: Structure) -> dict[str, object]:
    return {
        "name": layout.name,
        "requested_type": layout.requested_name,
        "kind": layout.kind,
        "size": layout.size,
        "alignment": layout.alignment,
        "members": [_member_dict(layout, member, None) for member in layout.members],
    }


def _member_dict(
    layout: Structure, member: Member, dump: StructureDump | None
) -> dict[str, object]:
    value = None if dump is None else layout.value_for(member, dump.bytes)
    return {
        "name": member.name,
        "offset": member.offset,
        "size": member.size,
        "type": layout.symbols.type_name(member.type_die),
        "value": value,
        "observed": value is not None,
    }


def _value_dict(layout: Structure, value: ObservedValue) -> dict[str, object]:
    return {
        "name": value.path,
        "offset": value.offset,
        "size": value.size,
        "type": layout.symbols.type_name(value.type_die),
        "value": value.value,
        "observed": value.value is not None,
    }


def _should_show(member: Member, dump: StructureDump, show_all: bool) -> bool:
    if show_all or member.offset is None or member.size is None:
        return show_all
    observed = dump.observed_offsets
    return any(member.offset <= offset < member.offset + member.size for offset in observed)


def _print_dump(
    dump: StructureDump, layout: Structure, show_all: bool, context: TypeContext
) -> None:
    vcpu = f", vcpu {dump.vcpu}" if dump.vcpu is not None else ""
    vm = f", {context.vm_type.upper()} VM" if context.vm_type is not None else ""
    print(f"{dump.declared_type} @ 0x{dump.address:016x}{vcpu}")
    print(f"resolved as {layout.kind} {layout.name}, {layout.size or '?'} bytes{vm}")
    if not show_all:
        for value in layout.observed_values(dump.bytes, context):
            offset = f"0x{value.offset:04x}"
            member_type = layout.symbols.type_name(value.type_die)
            rendered = value.value or "<unavailable>"
            print(f"  {offset:>6} {value.path:<48} {member_type:<36} {rendered}")
        return
    for member in layout.members:
        if not _should_show(member, dump, show_all):
            continue
        offset = "?" if member.offset is None else f"0x{member.offset:04x}"
        value = layout.value_for(member, dump.bytes) or "<unavailable>"
        member_type = layout.symbols.type_name(member.type_die)
        print(f"  {offset:>6} {member.name:<32} {member_type:<36} {value}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Explore Xen structure dumps using DWARF symbols")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect", help="resolve values present in a structure dump")
    inspect.add_argument("dump", type=Path, help="structure dump text file")
    inspect.add_argument("symbols", type=Path, help="Xen ELF symbol file with DWARF information")
    inspect.add_argument(
        "--all", action="store_true", help="also print members absent from an abridged dump"
    )
    inspect.add_argument("--json", action="store_true", help="emit JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""

    args = _parser().parse_args(argv)
    try:
        dumps = load_dump(args.dump)
        if not dumps:
            raise CrashAnalyzerError(f"no structure records found in {args.dump}")
        with SymbolFile(args.symbols) as symbols:
            layouts = [symbols.structure(dump.declared_type) for dump in dumps]
            domain_contexts = {
                dump.address: layout.context(dump.bytes)
                for dump, layout in zip(dumps, layouts, strict=True)
                if layout.name == "domain" and layout.context(dump.bytes).vm_type is not None
            }
            resolved: list[dict[str, object]] = []
            for dump, layout in zip(dumps, layouts, strict=True):
                vm_type = layout.vm_type(dump.bytes)
                context = layout.context(dump.bytes)
                if vm_type is None and layout.name == "vcpu":
                    domain_member = next(
                        (member for member in layout.members if member.name == "domain"), None
                    )
                    if domain_member is not None and domain_member.offset is not None:
                        domain_pointer = dump.read(domain_member.offset, domain_member.size or 0)
                        if domain_pointer is not None:
                            context = domain_contexts.get(
                                int.from_bytes(domain_pointer, symbols.byteorder), TypeContext()
                            )
                if context.vm_type is None and vm_type is not None:
                    context = TypeContext(
                        vm_type=cast(Literal["pv", "hvm"], vm_type),
                        nested_virt=context.nested_virt,
                    )
                if args.json:
                    resolved.append(
                        {
                            "declared_type": dump.declared_type,
                            "address": f"0x{dump.address:x}",
                            "vcpu": dump.vcpu,
                            "vm_type": context.vm_type,
                            "layout": _layout_dict(layout),
                            "members": (
                                [_member_dict(layout, member, dump) for member in layout.members]
                                if args.all
                                else [
                                    _value_dict(layout, value)
                                    for value in layout.observed_values(dump.bytes, context)
                                ]
                            ),
                        }
                    )
                else:
                    _print_dump(dump, layout, args.all, context)
                    print()
            if args.json:
                print(json.dumps(resolved, indent=2))
        return 0
    except CrashAnalyzerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
