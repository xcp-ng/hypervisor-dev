"""Command-line argument parsing."""

import argparse
import os

from .constants import CacheFlags, Mode


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--repository",
        type=str,
        default=".",
        help="Path to git repository (default: current directory)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_false",
        default=True,
        dest="cache",
        help="Disable patchid caching",
    )


def _finalize_args(args: argparse.Namespace) -> argparse.Namespace:
    args.repository = os.path.expanduser(args.repository)

    args.cache_flags = CacheFlags(0)
    if args.cache:
        args.cache_flags = CacheFlags.READ_FROM_CACHE | CacheFlags.WRITE_TO_CACHE

    return args


def parse_args(argv: None | list[str] = None) -> argparse.Namespace:
    """Parse the git-review-rebase arguments and return them."""
    parser = argparse.ArgumentParser(
        prog="git-review-rebase", description="Interactive tool for reviewing rebased git branches"
    )
    _add_common_args(parser)
    parser.add_argument(
        "--no-upstream-patchid",
        dest="upstream_patchid_lookup",
        action="store_false",
        default=True,
        help="Do not perform patch-id calculation for ancestors of the right range.",
    )
    parser.add_argument("left_range", help="Left range in format: base..branch")
    parser.add_argument("right_range", help="Right range in format: base..branch")
    parser.add_argument(
        "paths", nargs="*", metavar="PATH", help="Limit to commits touching these paths"
    )
    args = parser.parse_args(argv)

    args.mode = Mode.Rebase
    args.name_rev = True
    args.left_title = args.left_range.split("..")[1]
    args.right_title = args.right_range.split("..")[1]
    return _finalize_args(args)


def parse_spec_patches_args(argv: None | list[str] = None) -> argparse.Namespace:
    """Parse the git-spec-patches arguments and return them."""
    parser = argparse.ArgumentParser(
        prog="git-spec-patches",
        description="Generate the Patch lines of a spec file, and their patch files, from a "
        "patch-queue imported from a SRPM and its rebased version",
    )
    _add_common_args(parser)
    parser.add_argument(
        "-o",
        "--output-dir",
        required=True,
        help="Directory to write the patch files to, e.g. the SOURCES directory of the SRPM",
    )
    parser.add_argument(
        "--remote",
        default="vates",
        help="Remote to look for the XenServer branch the left branch is based on, whose tip "
        "ends the XenServer patch-queue (default: vates)",
    )
    parser.add_argument(
        "--end-xenserver-patchqueue",
        default=None,
        metavar="COMMIT",
        help="Last commit of the XenServer patch-queue in the left range, the following commits "
        "forming our own block (default: the tip of the XenServer branch found on --remote, "
        "else the last abi-version commit, else the end of the left range)",
    )
    parser.add_argument(
        "--ours-start",
        type=int,
        default=1000,
        help="Index of the first Patch line of our own block (default: 1000)",
    )
    parser.add_argument(
        "left_range", help="Imported patch-queue, starting at Patch0, in format: base..branch"
    )
    parser.add_argument("right_range", help="Rebased patch-queue in format: base..branch")
    args = parser.parse_args(argv)

    for r in (args.left_range, args.right_range):
        start, sep, end = r.partition("..")
        if not sep or not start or not end:
            parser.error(f"range must be in format base..branch, got '{r}'")

    args.paths = []
    args.upstream_patchid_lookup = True
    return _finalize_args(args)


def parse_backports_args(argv: None | list[str] = None) -> argparse.Namespace:
    """Parse the git-review-backports arguments and return them."""
    parser = argparse.ArgumentParser(
        prog="git-review-backports",
        description="Interactive tool for reviewing backports against their upstream commits",
    )
    _add_common_args(parser)
    parser.add_argument(
        "--upstream",
        type=str,
        default=None,
        help="Flag the backports whose upstream commit has fixes (Fixes: tags) in this branch "
        "which were not backported, e.g. origin/master",
    )
    parser.add_argument("range", help="Range of backported commits in format: base..branch")
    parser.add_argument(
        "paths", nargs="*", metavar="PATH", help="Limit to commits touching these paths"
    )
    args = parser.parse_args(argv)

    start, sep, end = args.range.partition("..")
    if not sep or not start or not end:
        parser.error(f"range must be in format base..branch, got '{args.range}'")

    args.mode = Mode.Backports
    args.name_rev = False
    args.left_title = "upstream"
    args.right_title = end
    return _finalize_args(args)
