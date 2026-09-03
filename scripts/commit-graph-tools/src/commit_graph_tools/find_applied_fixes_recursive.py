import argparse
import re
import subprocess
import sys

TREE_RANGE = "v4.19.19..HEAD"
REPOSITORY = "."


def git(*args):
    return subprocess.check_output(
        ["git", "-C", REPOSITORY, *args],
        text=True,
        errors="replace",
    )


def load_tree_subjects():
    """
    Return:
        subject -> [commit hashes]

    Only commits in TREE_RANGE are considered.
    """
    data = git(
        "log",
        TREE_RANGE,
        "--format=%H%x1f%s",
    )

    subjects = {}

    for line in data.splitlines():
        if "\x1f" not in line:
            continue

        commit_hash, subject = line.split("\x1f", 1)
        subjects.setdefault(subject, []).append(commit_hash)

    return subjects


def parse_fixes(lines):
    """
    Parse output from the recursive Fixes script while preserving depth.

    Input:

        original commit
          Fixed-by: aaaaaaaaaaaa first fix
            Mentioned-by: bbbbbbbbbbbb mention of first fix
              Fixed-by: cccccccccccc fix of mention

        another commit
          Error: no matching Fixes: tag or commit-message mention found

    Returns:
        [
            (
                "original commit",
                [
                    (1, "Fixed-by", "aaaaaaaaaaaa", "first fix", None),
                    (
                        2,
                        "Mentioned-by",
                        "bbbbbbbbbbbb",
                        "mention of first fix",
                        "title",
                    ),
                    (3, "Fixed-by", "cccccccccccc", "fix of mention", None),
                ],
            ),
            ...
        ]
    """
    groups = []
    current_source = None
    current_fixes = []

    ignored_statuses = {
        "no Fixes: commits found",
        "SOURCE NOT FOUND",
    }

    for raw in lines:
        line = raw.rstrip()

        if not line.strip():
            continue

        if line[0].isspace():
            if current_source is None:
                continue

            stripped = line.strip()

            if stripped in ignored_statuses or stripped.startswith("Error:"):
                continue

            # The first script uses two spaces per recursion level.
            leading_spaces = len(line) - len(line.lstrip(" "))

            # Be tolerant of odd indentation, but never produce depth 0
            # for an indented fix line.
            depth = max(1, leading_spaces // 2)

            match = re.fullmatch(
                r"(Fixed-by|Mentioned-by):\s+"
                r"([0-9a-fA-F]{7,40})\s+(.+)",
                stripped,
            )

            if match:
                relationship, upstream_hash, subject = match.groups()
                matched_as = None

                if relationship == "Mentioned-by":
                    annotation = re.fullmatch(
                        r"(.+) \(as (title|[0-9a-fA-F]{7,12})\)",
                        subject,
                    )

                    if annotation:
                        subject, matched_as = annotation.groups()
            else:
                # Retain compatibility with output from older versions of
                # find-fixers-recursive.py, which had no relationship label.
                parts = stripped.split(maxsplit=1)

                if len(parts) != 2:
                    print(
                        f"warning: cannot parse related commit: {line!r}",
                        file=sys.stderr,
                    )
                    continue

                upstream_hash, subject = parts
                relationship = "Fixed-by"
                matched_as = None

            if not (
                7 <= len(upstream_hash) <= 40
                and all(c in "0123456789abcdefABCDEF" for c in upstream_hash)
            ):
                print(
                    f"warning: ignoring malformed relationship: {line!r}",
                    file=sys.stderr,
                )
                continue

            current_fixes.append((depth, relationship, upstream_hash, subject, matched_as))

        else:
            if current_source is not None:
                groups.append((current_source, current_fixes))

            current_source = line.strip()
            current_fixes = []

    if current_source is not None:
        groups.append((current_source, current_fixes))

    return groups


def main():
    global REPOSITORY

    parser = argparse.ArgumentParser(
        description=(
            f"Find related commits already present in {TREE_RANGE}, "
            "preserving recursive relationship chains."
        )
    )

    parser.add_argument(
        "file",
        nargs="?",
        help="recursive Fixes-list file; omit or use - for stdin",
    )

    parser.add_argument(
        "-C",
        "--repo",
        default=REPOSITORY,
        metavar="PATH",
        help="repository to inspect (default: current directory)",
    )

    parser.add_argument(
        "--missing",
        action="store_true",
        help="show related commits NOT present instead of those already present",
    )

    parser.add_argument(
        "--show-local-hash",
        action="store_true",
        help="show matching hash from the current tree",
    )

    args = parser.parse_args()
    REPOSITORY = args.repo

    repository_check = subprocess.run(
        ["git", "-C", REPOSITORY, "rev-parse", "--git-dir"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    if repository_check.returncode != 0:
        parser.error(f"cannot access Git repository: {REPOSITORY}")

    if args.file and args.file != "-":
        with open(args.file, encoding="utf-8") as f:
            groups = parse_fixes(f)
    else:
        groups = parse_fixes(sys.stdin)

    tree_subjects = load_tree_subjects()

    total = 0
    matched = 0

    for source, fixes in groups:
        output = []

        for depth, relationship, upstream_hash, subject, matched_as in fixes:
            total += 1

            local_hashes = tree_subjects.get(subject, [])
            present = bool(local_hashes)

            if present:
                matched += 1

            want = not args.missing

            if present != want:
                continue

            indent = "  " * depth
            suffix = f" (as {matched_as})" if matched_as else ""

            if args.show_local_hash and present:
                local = ", ".join(h[:12] for h in local_hashes)

                output.append(
                    f"{indent}{relationship}: {upstream_hash} {subject}{suffix}    [local: {local}]"
                )
            else:
                output.append(f"{indent}{relationship}: {upstream_hash} {subject}{suffix}")

        if output:
            print(source)

            for line in output:
                print(line)

    if args.missing:
        print(
            f"\n{total - matched}/{total} related commits are not present in {TREE_RANGE}",
            file=sys.stderr,
        )
    else:
        print(
            f"\n{matched}/{total} related commits are already present in {TREE_RANGE}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
