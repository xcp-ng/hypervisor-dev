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


def parse_backports_args(argv: None | list[str] = None) -> argparse.Namespace:
    """Parse the git-review-backports arguments and return them."""
    parser = argparse.ArgumentParser(
        prog="git-review-backports",
        description="Interactive tool for reviewing backports against their upstream commits",
    )
    _add_common_args(parser)
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
