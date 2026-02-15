import difflib
import os
import re
import sys


def pretty(s):
    s = s.replace(" ;", ";\n")
    s = s.replace("{", "{\n")
    s = s.replace("}", "\n}")
    s = re.sub(r"([\[\(\*]) ", lambda m: m.group(1), s)
    s = re.sub(r" ([\]\),])", lambda m: m.group(1), s)
    final_result = []
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


def print_diffs(diffs, st1, st2, desc1="kABI", desc2="Build"):
    for orig, v1, v2 in diffs:
        name = st1.name(orig)
        sys.stdout.writelines(
            difflib.unified_diff(
                [line + "\n" for line in st1.gen_short_decl(v1).split("\n")],
                [line + "\n" for line in st2.gen_short_decl(v2).split("\n")],
                fromfile="{} - {}".format(name, desc1),
                tofile="{} - {}".format(name, desc2),
            )
        )
        print()


def collect_helper(directory, output, minimize_kabi, verbose=True):
    from .symtypes import SymTypes

    st = SymTypes()
    for dirpath, dirnames, filenames in os.walk(directory):
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


def compare_helper(symtypes_lhs, symtypes_rhs, print_missing=False, print_symbols=True):
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
    diffs = set()
    ret = 0
    diff_syms = []
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
