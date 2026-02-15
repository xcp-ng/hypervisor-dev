import os
import shutil
import sys
import tempfile
import zlib

from .fileio import read_lockedlist, read_symbols, read_symvers
from .symtypes import SymTypes
from .utils import collect_helper, compare_helper, print_diffs


def check(args):
    symvers_kabi = read_symvers(args.symvers_kabi)
    symvers_build = read_symvers(args.symvers_build)

    changed_license = []
    moved = []
    changed_abi = []
    unexported = []
    for sym, (hash_, dir_, type_) in symvers_kabi.items():
        if sym not in symvers_build:
            unexported.append(sym)
            continue
        build_hash, build_dir, build_type = symvers_build[sym]
        if build_hash != hash_:
            changed_abi.append(sym)
        if build_dir != dir_:
            moved.append(sym)
        if build_type != type_:
            changed_license.append(sym)
    if moved:
        print("*** WARNING - ABI SYMBOLS MOVED ***")
        print()
        print("The following symbols moved (typically caused by moving a symbol from being")
        print("provided by the kernel vmlinux out to a loadable module). This is not an")
        print("error, but is being reported for completeness:")
        print()
        print("\n".join(moved))
        print()
    if changed_license:
        print("*** ERROR - SYMBOL LICENSE HAS CHANGED ***")
        print()
        print(
            "The usage license for the following symbols has changed"
            " (this will cause an ABI breakage):"
        )
        print()
        print("\n".join(changed_license))
        print()
    if changed_abi:
        print("*** ERROR - ABI BREAKAGE WAS DETECTED ***")
        print()
        print("The following symbols have been changed (this will cause an ABI breakage):")
        print("For help diagnosing why, please see the diffs below the listing.")
        print()
        print("\n".join(changed_abi))
        print()
    if unexported:
        print("*** ERROR - ABI SYMBOL WAS REMOVED ***")
        print()
        print("The following symbols have been removed, or unexported. This will cause")
        print("an ABI breakage:")
        print()
        print("\n".join(unexported))
        print()

    if not changed_license and not changed_abi and not unexported:
        sys.exit(0)

    if not changed_abi:
        sys.exit(1)

    if not args.symtypes_kabi or not args.symtypes_build:
        print("*** MISSING --symtypes-kabi AND --symtypes-build ***")
        print()
        print("Without this information, we cannot provide detailed diagnostics.")
        sys.exit(1)

    st_kabi = SymTypes.from_file(args.symtypes_kabi)
    st_build = SymTypes.from_file(args.symtypes_build)

    print("*** DETECTED TYPE DIFFERENCES ***")
    print()
    diffs = set()
    for symbol in changed_abi:
        diffs |= SymTypes.identify_kabi_difference(st_kabi, st_build, symbol)
    print_diffs(diffs, st_kabi, st_build)

    sys.exit(1)


def report(args):
    t = SymTypes.from_file(args.symtypes)
    for exported, filename in t.exports.items():
        decl = t.gen(exported, filename)
        crc = zlib.crc32(decl.encode()) & 0xFFFFFFFF
        print(f"0x{crc:08x}\t{exported}")


def collect(args):
    kabi_syms = None
    if args.minimize_kabi:
        kabi_syms = read_symbols(args.minimize_kabi)
    return collect_helper(args.directory, args.output, kabi_syms)


def consolidate(args):
    st = SymTypes.from_file(args.input)
    if args.kabi:
        symbols = read_symbols(args.kabi)
        st.filter_exports(symbols, True)
    with open(args.output, "w") as f:
        st.write(f)


def compare(args):
    return compare_helper(
        args.symtypes_lhs, args.symtypes_rhs, args.print_missing, args.print_symbols
    )


def debug(args):
    tmp = tempfile.mkdtemp()
    symtypes_build = os.path.join(tmp, "Symtypes.build")
    try:
        minimize_kabi = set(SymTypes.from_file(args.symtypes).exports.keys())
        collect_helper(args.directory, symtypes_build, minimize_kabi, verbose=False)
        compare_helper(symtypes_build, args.symtypes, True, True)
    finally:
        shutil.rmtree(tmp)


def smoke(args):
    kabi_st = SymTypes.from_file(args.symtypes)
    kabi_st_syms = set(kabi_st.exports.keys())
    kabi_sv = read_symvers(args.symvers)
    kabi_sv_syms = set(kabi_sv.keys())
    lockedlist = read_lockedlist(args.lockedlist)
    ret = 0
    sv_only = kabi_sv_syms - lockedlist
    ll_only = lockedlist - kabi_sv_syms
    if sv_only:
        print("ERROR: Module.kabi contains symbols not in kabi_lockedlist!")
        print("\n".join(sorted(sv_only)))
        ret = 1
    if ll_only:
        print("ERROR: kabi_lockedlist contains symbols not in Module.kabi!")
        print("\n".join(sorted(ll_only)))
        ret = 1

    st_only = kabi_st_syms - kabi_sv_syms
    sv_only = kabi_sv_syms - kabi_st_syms
    if sv_only:
        print("ERROR: Module.kabi contains symbols not in Symtypes.kabi!")
        print("\n".join(sorted(sv_only)))
        ret = 1
    if st_only:
        print("ERROR: Symtypes.kabi contains symbols not in Module.kabi!")
        print("\n".join(sorted(st_only)))
        ret = 1
    differing_syms = []
    common_syms = kabi_st_syms & kabi_sv_syms
    for sym in common_syms:
        crc = int(kabi_sv[sym][0], 16)
        computed_crc = kabi_st.crc(sym, kabi_st.exports[sym])
        if computed_crc != crc:
            differing_syms.append((sym, crc, computed_crc))
    if differing_syms:
        differing_syms.sort()
        print(
            "ERROR: some symbol versions computed via Symtypes.kabi do not "
            "match their corresponding entries from Module.kabi:"
        )
        print("Computed\tRecorded\tSymbol")
        for sym, crc, computed_crc in differing_syms:
            print(f"{computed_crc:08x}\t{crc:08x}\t{sym}")
        ret = 1

    if ret:
        print("NOTE: These smoke tests errors do not indicate kABI breakages.")
        print("Instead, they indicate an error in the maintenance of UEK kABI.")
        print("Unless you've modified Module.kabi or Symtypes.kabi, you should")
        print("report these to the UEK maintainers.")
    sys.exit(ret)
