import argparse
import sys

from . import commands


def main() -> None:
    p = argparse.ArgumentParser(
        description="kABI checking and diagnostics",
    )
    subp = p.add_subparsers(title="sub-command")

    report_p = subp.add_parser(
        "report",
        help=(
            "Compute and report symbol versions using only data from "
            "a symtypes file. Mostly for debugging this script."
        ),
    )
    report_p.set_defaults(func=commands.report)
    report_p.add_argument("symtypes", help="symtypes file or collection")

    check_p = subp.add_parser(
        "check",
        help=(
            "Compare Module.symvers with Module.kabi. If kABI is broken, "
            "print a report. If both symtypes files are provided, then "
            "broken kABI will also trigger a diagnostic that identifies "
            "the type declarations causing the breakage."
        ),
    )
    check_p.set_defaults(func=commands.check)
    check_p.add_argument(
        "--symvers-kabi",
        "-k",
        help="Module.kabi file (the kABI declaration)",
        required=True,
    )
    check_p.add_argument(
        "--symvers-build",
        "-s",
        help="Module.symvers file (created from a recent build)",
        required=True,
    )
    check_p.add_argument(
        "--symtypes-kabi",
        "-K",
        help="Symtypes.kabi file (symtypes collection from kABI)",
    )
    check_p.add_argument(
        "--symtypes-build",
        "-S",
        help="Symtypes.build file (symtypes collection from build)",
    )

    collect_p = subp.add_parser(
        "collect",
        help="Collect all symtypes files from a kernel build to a file",
    )
    collect_p.set_defaults(func=commands.collect)
    collect_p.add_argument(
        "directory",
        help="directory to search recursively",
    )
    collect_p.add_argument(
        "-o",
        "--output",
        default="Symtypes.build",
        help="File to write the collection to",
    )
    collect_p.add_argument(
        "--minimize-kabi",
        help=(
            "A Module.kabi or kabi_lockedlist file to use for minimizing "
            "the size of the Symtypes. Similar in operation to the "
            "consolidate subcommand."
        ),
    )

    consolidate_p = subp.add_parser(
        "consolidate",
        help=(
            "Given a kABI, filter the Symtypes to just data necessary "
            "to validate kABI symbols. With no kABI, just reads and "
            "re-writes the Symtypes, which could be good for testing."
        ),
    )
    consolidate_p.set_defaults(func=commands.consolidate)
    consolidate_p.add_argument(
        "--input",
        "-i",
        help="Input Symtypes",
        required=True,
    )
    consolidate_p.add_argument(
        "--output",
        "-o",
        help="Output Symtypes",
        required=True,
    )
    consolidate_p.add_argument(
        "--kabi",
        "-k",
        help=(
            "Module.symvers or kabi_lockedlist containing the list of kABI symbols to filter to."
        ),
    )

    compare_p = subp.add_parser(
        "compare",
        help="Given two Symtypes files, compare all exported symbols in both.",
    )
    compare_p.set_defaults(func=commands.compare)
    compare_p.add_argument(
        "symtypes_lhs",
        help="Symtypes file for baseline (e.g. kABI reference)",
    )
    compare_p.add_argument(
        "symtypes_rhs",
        help=("Symtypes file for comparison (e.g. mm/slub.symtypes or Symtypes.build)"),
    )
    compare_p.add_argument(
        "--no-print-symbols",
        action="store_false",
        dest="print_symbols",
        help=(
            "Do not print the symbols whose symvers differ. Only print the "
            "underlying type differences."
        ),
    )
    compare_p.add_argument(
        "--print-missing",
        action="store_true",
        help="Print symbols which are present in only one of the files.",
    )

    debug_p = subp.add_parser(
        "debug",
        help=(
            "Given a local build directory, compare against a Symtypes.kabi. "
            "Roughly equivalent to running collect, consolidate, and then "
            "compare."
        ),
    )
    debug_p.set_defaults(func=commands.debug)
    debug_p.add_argument(
        "directory",
        help="local full build directory",
    )
    debug_p.add_argument(
        "symtypes",
        help="kABI symtypes file",
    )

    smoke_p = subp.add_parser(
        "smoke",
        help="Smoke test a given lockedlist, Module.kabi, and Symtypes.kabi",
    )
    smoke_p.set_defaults(func=commands.smoke)
    smoke_p.add_argument(
        "--symtypes",
        "-t",
        help="Symtypes.kabi file",
    )
    smoke_p.add_argument(
        "--symvers",
        "-v",
        help="Module.kabi file",
    )
    smoke_p.add_argument(
        "--lockedlist",
        "-l",
        help="kabi_lockedlist file",
    )

    tui_p = subp.add_parser(
        "tui",
        help="Opens an interactive user interface to help fixing kABI changes",
    )
    tui_p.set_defaults(func=commands.tui)
    tui_p.add_argument(
        "--locked-file",
        "-l",
        required=True,
        metavar="KABI.LOCKED_FILE",
        help="Path to the kabi.locked_file (e.g. xcpng-8.3-kabi.locked_list)",
    )
    tui_p.add_argument(
        "--repository",
        "-r",
        default="./",
        help="Path to the git repository hosting the source code",
    )
    tui_p.add_argument(
        "--rev-list",
        required=True,
        help="Options passed to git rev-list to get the list of commits to audit (e.g. v4.19.19..v4.19.325)",
    )
    tui_p.add_argument(
        "--old-vmlinux",
        metavar="VMLINUX.O",
        required=False,
        help="Unstripped vmlinux.o file before changes",
    )
    tui_p.add_argument(
        "--new-vmlinux",
        metavar="VMLINUX.O",
        required=False,
        help="Unstripped vmlinux.o file after changes",
    )
    tui_p.add_argument(
        "symtypes_lhs",
        metavar="Modules.kabi|Symtypes.build",
        help="Symtypes file for baseline (e.g. kABI Modules.kabi-v4.19.19)",
    )
    tui_p.add_argument(
        "symtypes_rhs",
        metavar="Modules.kabi|Symtypes.build",
        help=("Symtypes file for comparison (e.g. Symtypes.build-v4.19.325)"),
    )

    args = p.parse_args()
    if not getattr(args, "func", None):
        p.print_help()
        sys.exit(1)
    args.func(args)
