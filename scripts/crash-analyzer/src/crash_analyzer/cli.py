"""Command-line interface for the Xen structure dump explorer."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO

from .dump import StructureDump, load_dump
from .dwarf import Member, ObservedValue, Structure, SymbolFile, TypeContext
from .errors import CrashAnalyzerError


def _is_padding(name: str) -> bool:
    return any(
        re.fullmatch(r"_?pad[0-9]*", part.split("[", 1)[0]) is not None for part in name.split(".")
    )


def _layout_dict(layout: Structure) -> dict[str, object]:
    return {
        "name": layout.name,
        "requested_type": layout.requested_name,
        "kind": layout.kind,
        "size": layout.size,
        "alignment": layout.alignment,
        "members": [
            _member_dict(layout, member, None)
            for member in layout.members
            if not _is_padding(member.name)
        ],
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


def _print_dump(
    dump: StructureDump,
    layout: Structure,
    data: dict[int, int],
    show_all: bool,
    context: TypeContext,
    output: IO[str],
) -> None:
    vcpu = f", vcpu {dump.vcpu}" if dump.vcpu is not None else ""
    vm = f", {context.vm_type.upper()}" if context.vm_type is not None else ""
    backend = f", {context.hvm_backend.upper()}" if context.hvm_backend is not None else ""
    print(f"{dump.declared_type} @ 0x{dump.address:016x}{vcpu}", file=output)
    print(
        f"resolved as {layout.kind} {layout.name}, {layout.size or '?'} bytes{vm}{backend}",
        file=output,
    )
    for value in layout.observed_values(data, context, all_branches=show_all):
        if _is_padding(value.path):
            continue
        offset = f"0x{value.offset:04x}"
        member_type = layout.symbols.type_name(value.type_die)
        rendered = value.value or "<unavailable>"
        print(f"  {offset:>6} {value.path:<48} {member_type:<36} {rendered}", file=output)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Decode Xen structure dumps into one parsed file per input using DWARF symbols"
    )
    parser.add_argument("symbols", type=Path, help="Xen ELF symbol file with DWARF information")
    parser.add_argument("dumps", type=Path, nargs="+", help="structure dump text files")
    parser.add_argument(
        "--all",
        action="store_true",
        help="also print union branches excluded by the resolved context",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="write .parsed.json files instead of human-readable .parsed.log files",
    )
    return parser


def _resolve_file(
    path: Path, symbols: SymbolFile, layouts: dict[str, Structure]
) -> Iterator[tuple[StructureDump, Structure, dict[int, int], TypeContext]]:
    """Resolve one snapshot, sharing layouts but keeping runtime context local."""

    dumps = load_dump(path)
    if not dumps:
        raise CrashAnalyzerError(f"no structure records found in {path}")
    entries = []
    for dump in dumps:
        if dump.declared_type not in layouts:
            layouts[dump.declared_type] = symbols.structure(dump.declared_type)
        entries.append((dump, layouts[dump.declared_type], dump.bytes))
    domain_contexts = {
        dump.address: layout.context(data)
        for dump, layout, data in entries
        if layout.name == "domain"
    }
    for dump, layout, data in entries:
        context = (
            domain_contexts.get(dump.address, TypeContext())
            if layout.name == "domain"
            else TypeContext()
        )
        if layout.name == "vcpu":
            domain_member = next(
                (member for member in layout.members if member.name == "domain"), None
            )
            if domain_member is not None and domain_member.offset is not None:
                domain_pointer = layout._value(data, domain_member.offset, domain_member.size)
                if domain_pointer is not None:
                    context = domain_contexts.get(
                        int.from_bytes(domain_pointer, symbols.byteorder), TypeContext()
                    )
        yield dump, layout, data, context


def _output_path(path: Path, as_json: bool) -> Path:
    stem = path.stem.removesuffix(".structures")
    return path.with_name(f"{stem}.parsed.{'json' if as_json else 'log'}")


def _write_output(
    path: Path,
    output: IO[str],
    symbols: SymbolFile,
    layouts: dict[str, Structure],
    json_layouts: dict[str, dict[str, object]],
    show_all: bool,
    as_json: bool,
) -> None:
    emitted = False
    if as_json:
        print("[", end="", file=output)
    for dump, layout, data, context in _resolve_file(path, symbols, layouts):
        if not as_json:
            _print_dump(dump, layout, data, show_all, context, output)
            print(file=output)
            continue
        if dump.declared_type not in json_layouts:
            json_layouts[dump.declared_type] = _layout_dict(layout)
        record = {
            "source": str(path),
            "declared_type": dump.declared_type,
            "address": f"0x{dump.address:x}",
            "vcpu": dump.vcpu,
            "vm_type": context.vm_type,
            "hvm_backend": context.hvm_backend,
            "layout": json_layouts[dump.declared_type],
            "members": [
                _value_dict(layout, value)
                for value in layout.observed_values(data, context, all_branches=show_all)
                if not _is_padding(value.path)
            ],
        }
        print("," if emitted else "", end="\n", file=output)
        print("  " + json.dumps(record, indent=2).replace("\n", "\n  "), end="", file=output)
        emitted = True
    if as_json:
        print("\n]" if emitted else "]", file=output)


def main(argv: Sequence[str] | None = None) -> int:
    """Write one output per dump file using one ELF/DWARF index."""

    args = _parser().parse_args(argv)
    status = 0
    layouts: dict[str, Structure] = {}
    json_layouts: dict[str, dict[str, object]] = {}
    inputs = {path.resolve() for path in [args.symbols, *args.dumps]}
    destinations: dict[Path, set[Path]] = {}
    for path in args.dumps:
        destinations.setdefault(_output_path(path, args.json).resolve(), set()).add(path.resolve())
    try:
        print("loading symbols", flush=True)
        with SymbolFile(args.symbols) as symbols:
            for path in args.dumps:
                temporary = None
                output_path = _output_path(path, args.json)
                try:
                    destination = output_path.resolve()
                    if destination in inputs:
                        raise CrashAnalyzerError(f"output {output_path} would overwrite an input")
                    if len(destinations[destination]) > 1:
                        raise CrashAnalyzerError(f"multiple inputs map to output {output_path}")
                    with NamedTemporaryFile(
                        mode="w",
                        encoding="utf-8",
                        dir=output_path.parent,
                        prefix=f".{output_path.name}.",
                        delete=False,
                    ) as output:
                        temporary = Path(output.name)
                        _write_output(
                            path, output.file, symbols, layouts, json_layouts, args.all, args.json
                        )
                    temporary.replace(output_path)
                    print(f"{path} -> {output_path}")
                except (CrashAnalyzerError, OSError) as exc:
                    print(f"error: {path}: {exc}", file=sys.stderr)
                    status = 2
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
        return status
    except CrashAnalyzerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
