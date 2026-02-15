import difflib
import os
import re
import sys
from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from .symtypes import SymTypes


def pretty(s: str, enum_mode: bool = False) -> str:
    s = s.replace(" ;", ";\n")
    s = s.replace("{", "{\n")
    s = s.replace("}", "\n}")
    if enum_mode:
        s = s.replace(", ", ",\n")
    s = re.sub(r"([\[\(\*]) ", lambda m: m.group(1), s)
    s = re.sub(r" ([\]\),])", lambda m: m.group(1), s)
    final_result: list[str] = []
    indent = 0
    for line in s.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line[0] == "}":
            indent -= 1
        final_result.append("\t" * indent + line)
        if line[-1] == "{":
            indent += 1
    return "\n".join(final_result)


def print_diffs(
    diffs: set[tuple[str, str, str]],
    st1: "SymTypes",
    st2: "SymTypes",
    desc1: str = "kABI",
    desc2: str = "Build",
) -> None:
    for orig, v1, v2 in diffs:
        name = st1.name(orig)
        sys.stdout.writelines(
            difflib.unified_diff(
                [line + "\n" for line in st1.gen_short_decl(v1).split("\n")],
                [line + "\n" for line in st2.gen_short_decl(v2).split("\n")],
                fromfile=f"{name} - {desc1}",
                tofile=f"{name} - {desc2}",
            )
        )
        print()


def collect_helper(
    directory: str, output: str, minimize_kabi: set[str] | None, verbose: bool = True
) -> None:
    from .symtypes import SymTypes

    st = SymTypes()
    for dirpath, _dirnames, filenames in os.walk(directory):
        for fn in filenames:
            if fn.endswith(".symtypes"):
                file_path = os.path.join(dirpath, fn)
                with open(file_path) as fp:
                    relative_path = os.path.relpath(file_path, directory)
                    st.add_file(fp, relative_path)
    st.consolidate_symvers()
    if minimize_kabi:
        st.filter_exports(minimize_kabi, verbose)
    with open(output, "w") as fp:
        st.write(fp)


def compare_helper(
    symtypes_lhs: str, symtypes_rhs: str, print_missing: bool = False, print_symbols: bool = True
) -> NoReturn:
    from .symtypes import SymTypes

    st_lhs = SymTypes.from_file(symtypes_lhs)
    st_rhs = SymTypes.from_file(symtypes_rhs)
    lhs_syms = set(st_lhs.exports.keys())
    rhs_syms = set(st_rhs.exports.keys())
    common_symbols = lhs_syms & rhs_syms
    if not common_symbols:
        print("error: these share no symbols in common, nothing to compare!")
        sys.exit(1)
    if print_missing:
        lhs_only = lhs_syms - rhs_syms
        if lhs_only:
            print("The following symbols appear only in the Baseline:")
            print("\n".join(lhs_only))
        rhs_only = rhs_syms - lhs_syms
        if rhs_only:
            print("The following symbols appear only in the Comparison:")
            print("\n".join(rhs_only))
    diffs: set[tuple[str, str, str]] = set()
    ret = 0
    diff_syms: list[str] = []
    for symbol in common_symbols:
        if st_lhs.crc(symbol) != st_rhs.crc(symbol):
            diff_syms.append(symbol)
            ret = 1
            diffs |= SymTypes.identify_kabi_difference(st_lhs, st_rhs, symbol)
    if print_symbols:
        print("The following symbols differ:")
        print("\n".join(diff_syms))
    print_diffs(diffs, st_lhs, st_rhs, "Baseline", "Comparison")
    sys.exit(ret)
