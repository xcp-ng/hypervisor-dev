"""Generate the Patch lines of a SRPM spec file, and their patch files, from a rebased branch.

The left range is a patch-queue imported from a SRPM (e.g. with git-import-srpm), applied in the
order of its Patch lines, starting at Patch0.  The right range is the same patch-queue rebased onto
a new base.  Every left commit keeps its spec index:

- if it was rebased, the right commit is exported with git format-patch,
- if it is already present in the new base, it becomes a comment referencing the upstream commit,
- if it was dropped, it becomes a TODO comment to be filled in.

The left commits up to the end of the XenServer patch-queue keep their exact index, so that the
generated block can be diffed against the XenServer spec file.  The following left commits, and
the commits only present on the right, form our own block, numbered sequentially from
--ours-start in the order they are applied on the right.  Commits only present on the right must
come after the XenServer block.

The end of the XenServer patch-queue is, in order of preference:

- the commit given with --end-xenserver-patchqueue,
- the tip of the XenServer branch the left branch is based on, i.e.
  <remote>/<product>/xenserver-<version>/patched for <product>/xcpng-<version>.<release>/patched,
- the last "abi-version" commit of the left range,
- the end of the left range.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass

import pygit2
from pygit2.enums import SortMode

from .branch_range import BranchRange
from .commit_matching import RebasedCommitMatch, RebasedCommitsMatches
from .constants import CommitMatchInfoFlag
from .git_utils import abbrev, commit_title, oid


class SpecPatchesError(Exception):
    """The ranges cannot be turned into spec Patch lines."""


@dataclass
class SpecEntry:
    """One PatchN line: a patch exported from a right commit, or a comment."""

    index: int
    commit: None | pygit2.Commit = None
    comment: str = ""
    filename: str = ""

    def line(self) -> str:
        if self.commit is not None:
            return f"Patch{self.index}: {self.filename}"
        return f"# Patch{self.index}: {self.comment}"


def linear_log(repo: pygit2.Repository, start: str, end: str) -> list[pygit2.Commit]:
    """Return the commits of start..end, oldest first, refusing merges."""
    walker = repo.walk(oid(repo, end), SortMode.TOPOLOGICAL | SortMode.REVERSE)
    walker.hide(oid(repo, start))
    commits = list(walker)
    for commit in commits:
        if len(commit.parents) > 1:
            raise SpecPatchesError(
                f"{start}..{end} is not linear, merge {abbrev(commit.id)} cannot be exported"
            )
    return commits


def describe(commit: pygit2.Commit) -> str:
    return f'{abbrev(commit.id)} ("{commit_title(commit)}")'


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


# Branches created by git-import-srpm, e.g. kernel/xcpng-4.19.19-8.0.46.17/patched.
XCPNG_BRANCH = re.compile(r"^(?P<product>.+)/xcpng-(?P<version>[^/]+)/patched$")

# Title of the last commit of the XenServer kernel patch-queue.
ABI_VERSION_TITLE = "abi-version"


def branch_name(repo: pygit2.Repository, revision: str) -> None | str:
    """Return the branch name of a revision, without its refs/heads/ or remote prefix."""
    try:
        ref = repo.lookup_reference_dwim(revision)
    except (KeyError, pygit2.InvalidSpecError):
        return None
    name = ref.name
    if name.startswith("refs/heads/"):
        return name.removeprefix("refs/heads/")
    for remote in repo.remotes.names():
        if remote is not None and name.startswith(f"refs/remotes/{remote}/"):
            return name.removeprefix(f"refs/remotes/{remote}/")
    return None


def xenserver_branch(repo: pygit2.Repository, remote: str, xcpng_branch: str) -> None | str:
    """Return the XenServer branch an XCP-ng branch is based on, from the given remote.

    Its version is the longest prefix of the XCP-ng version, e.g. 8.0.46 for 8.0.46.17."""
    match = XCPNG_BRANCH.match(xcpng_branch)
    if match is None:
        return None
    product, version = match.group("product"), match.group("version")
    pattern = f"refs/remotes/{remote}/{product}/xenserver-*/patched"
    output = subprocess.run(
        ["git", "-C", repo.path, "for-each-ref", "--format=%(refname)", pattern],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    prefix = f"refs/remotes/{remote}/{product}/xenserver-"
    candidates = []
    for ref in output.split():
        xenserver_version = ref.removeprefix(prefix).removesuffix("/patched")
        if version == xenserver_version or version.startswith(xenserver_version + "."):
            candidates.append((len(xenserver_version), ref))
    if not candidates:
        return None
    return max(candidates)[1].removeprefix("refs/remotes/")


class SpecPatches:
    """Spec entries of the XenServer block and of our own block."""

    def __init__(self, args: argparse.Namespace, repo: pygit2.Repository):
        self.args = args
        self.repo = repo
        self.xs_entries: list[SpecEntry] = []
        self.ours_entries: list[SpecEntry] = []
        # Left commits matched upstream on their title only, worth double checking.
        self.title_matches: list[SpecEntry] = []

        left_start, left_end = args.left_range.split("..", 1)
        right_start, right_end = args.right_range.split("..", 1)
        for revision in (left_start, left_end, right_start, right_end):
            try:
                oid(repo, revision + "^{commit}")
            except (KeyError, ValueError) as e:
                raise SpecPatchesError(f"unknown revision {revision}") from e
        left_start, left_end = left_start + "^{commit}", left_end + "^{commit}"
        right_start, right_end = right_start + "^{commit}", right_end + "^{commit}"

        self.left = linear_log(repo, left_start, left_end)
        self.right = linear_log(repo, right_start, right_end)
        if not self.left:
            raise SpecPatchesError(f"{args.left_range} is empty")
        self.xs_end = self.end_xenserver_index(args.left_range.split("..", 1)[1])

        merge_base = repo.merge_base(oid(repo, left_end), oid(repo, right_end))
        left_range = BranchRange(args, repo, left_start, left_end, args.cache_flags)
        right_range = BranchRange(
            args, repo, right_start, right_end, args.cache_flags, merge_base=merge_base
        )
        matches = RebasedCommitsMatches(args, repo, left_range, right_range)
        self.build(matches)

    def left_index(self, commit_id: pygit2.Oid) -> None | int:
        for i, commit in enumerate(self.left):
            if commit.id == commit_id:
                return i
        return None

    def end_xenserver_index(self, left_end: str) -> int:
        """Return the index of the last commit of the XenServer patch-queue in the left range."""
        if self.args.end_xenserver_patchqueue is not None:
            commit_id = oid(self.repo, self.args.end_xenserver_patchqueue + "^{commit}")
            index = self.left_index(commit_id)
            if index is None:
                raise SpecPatchesError(
                    f"--end-xenserver-patchqueue {self.args.end_xenserver_patchqueue} is not in "
                    f"{self.args.left_range}"
                )
            return index

        reason = self.xenserver_branch_index(left_end)
        if isinstance(reason, int):
            return reason

        for index in reversed(range(len(self.left))):
            if commit_title(self.left[index]) == ABI_VERSION_TITLE:
                warn(
                    f"{reason}, falling back to the last {ABI_VERSION_TITLE} commit of the left "
                    f"range: found {describe(self.left[index])}"
                )
                return index
        warn(
            f"{reason}, falling back to the last {ABI_VERSION_TITLE} commit of the left range: "
            "not found, the whole left range is considered as the XenServer patch-queue"
        )
        return len(self.left) - 1

    def xenserver_branch_index(self, left_end: str) -> int | str:
        """Return the index of the matching XenServer branch tip, or why it was not found."""
        name = branch_name(self.repo, left_end)
        if name is None:
            return f"{left_end} is not a branch"
        branch = xenserver_branch(self.repo, self.args.remote, name)
        if branch is None:
            return f"no XenServer branch matching {name} found on remote {self.args.remote}"
        index = self.left_index(oid(self.repo, branch + "^{commit}"))
        if index is None:
            return f"{branch} is not in {self.args.left_range}"
        print(
            f"XenServer patch-queue ends at {branch}: {describe(self.left[index])}",
            file=sys.stderr,
        )
        return index

    def build(self, matches: RebasedCommitsMatches) -> None:
        right_position = {commit.id: i for i, commit in enumerate(self.right)}
        by_left: dict[pygit2.Oid, RebasedCommitMatch] = {}
        added: list[pygit2.Commit] = []
        for match in matches.commit_matches.values():
            if match.left_commit is not None:
                by_left[match.left_commit.id] = match
            else:
                assert match.right_commit is not None
                added.append(match.right_commit)
        added.sort(key=lambda commit: right_position[commit.id])

        def rebased_position(match: RebasedCommitMatch) -> None | int:
            if match.right_commit is None:
                return None
            return right_position.get(match.right_commit.id)

        # Each rebased right commit must come from a single left commit, in the same order.
        errors: list[str] = []
        seen: dict[int, pygit2.Commit] = {}
        last = -1
        for left_commit in self.left:
            position = rebased_position(by_left[left_commit.id])
            if position is None:
                continue
            if position in seen:
                errors.append(
                    f"{describe(self.right[position])} matches both "
                    f"{describe(seen[position])} and {describe(left_commit)}"
                )
            elif position < last:
                errors.append(
                    f"{describe(left_commit)} was applied out of order, as "
                    f"{describe(self.right[position])}"
                )
            seen[position] = left_commit
            last = max(last, position)

        left_xs_end = self.xs_end
        # The XenServer block ends on the right with the last rebased XenServer commit.
        right_xs_end = max(
            (
                position
                for left_commit in self.left[: left_xs_end + 1]
                if (position := rebased_position(by_left[left_commit.id])) is not None
            ),
            default=-1,
        )
        for commit in added:
            if right_position[commit.id] < right_xs_end:
                errors.append(
                    f"{describe(commit)} is not in the left range and is applied within the "
                    f"XenServer block, it must come after {describe(self.right[right_xs_end])}"
                )
        for left_commit in self.left[left_xs_end + 1 :]:
            position = rebased_position(by_left[left_commit.id])
            if position is not None and position <= right_xs_end:
                errors.append(
                    f"{describe(left_commit)} comes after the end of the XenServer patch-queue "
                    f"but was applied within the XenServer block, as "
                    f"{describe(self.right[position])}"
                )
        if errors:
            raise SpecPatchesError("\n".join(errors))

        def left_entry(index: int, left_commit: pygit2.Commit) -> SpecEntry:
            match = by_left[left_commit.id]
            if rebased_position(match) is not None:
                return SpecEntry(index, commit=match.right_commit)
            if match.right_commit is not None:
                entry = SpecEntry(index, comment=describe(match.right_commit))
                if CommitMatchInfoFlag.LooseMatch in match.match_info:
                    self.title_matches.append(entry)
                return entry
            return SpecEntry(index, comment=f'TODO ("{commit_title(left_commit)}")')

        for index, left_commit in enumerate(self.left[: left_xs_end + 1]):
            self.xs_entries.append(left_entry(index, left_commit))

        # Our block: the left commits after the XenServer patch-queue, with the commits only
        # present on the right inserted before the first left commit applied after them.
        index = self.args.ours_start
        pending = list(added)
        for left_commit in self.left[left_xs_end + 1 :]:
            position = rebased_position(by_left[left_commit.id])
            while pending and position is not None and right_position[pending[0].id] < position:
                self.ours_entries.append(SpecEntry(index, commit=pending.pop(0)))
                index += 1
            self.ours_entries.append(left_entry(index, left_commit))
            index += 1
        for commit in pending:
            self.ours_entries.append(SpecEntry(index, commit=commit))
            index += 1

    def entries(self) -> list[SpecEntry]:
        return self.xs_entries + self.ours_entries

    def export(self, output_dir: str) -> None:
        """Write the patch file of each exported entry, numbered after its spec index.

        Nothing is written to output_dir unless all patches could be generated, and existing
        files are never overwritten."""
        exported = [entry for entry in self.entries() if entry.commit is not None]
        with tempfile.TemporaryDirectory() as tmp_dir:
            for entry in exported:
                assert entry.commit is not None
                entry.filename = self.format_patch(entry.commit, entry.index, tmp_dir)
            existing = [
                e.filename for e in exported if os.path.exists(os.path.join(output_dir, e.filename))
            ]
            if existing:
                raise SpecPatchesError(
                    f"{len(existing)} patches already exist in {output_dir}, refusing to "
                    f"overwrite them, e.g. {existing[0]}"
                )
            os.makedirs(output_dir, exist_ok=True)
            for entry in exported:
                shutil.move(
                    os.path.join(tmp_dir, entry.filename), os.path.join(output_dir, entry.filename)
                )

    def format_patch(self, commit: pygit2.Commit, index: int, output_dir: str) -> str:
        """Run git format-patch on the commit, numbered after its index, and return the name."""
        # Stable output regardless of the user's configuration (format.signOff, format.notes,
        # format.useAutoBase, format.suffix, diff.noprefix...): the commit exactly as it is, without
        # its sha1 nor the git version, a/ and b/ prefixes for patch -p1, a single [PATCH] prefix.
        command = [
            "git",
            "-C",
            self.repo.workdir,
            "format-patch",
            "-1",
            "--zero-commit",
            "--no-signature",
            "--no-signoff",
            "--no-notes",
            "--no-base",
            "--no-numbered",
            "--no-thread",
            "--no-cover-letter",
            "--suffix=.patch",
            "--src-prefix=a/",
            "--dst-prefix=b/",
            "--start-number",
            str(index),
            "-o",
            output_dir,
            str(commit.id),
        ]
        path = subprocess.run(command, capture_output=True, text=True, check=True).stdout.strip()
        return os.path.basename(path)


def main(args: argparse.Namespace) -> int:
    repo = pygit2.Repository(args.repository)
    try:
        spec = SpecPatches(args, repo)
        spec.export(args.output_dir)
    except SpecPatchesError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    lines = [entry.line() for entry in spec.xs_entries]
    lines += [""] + [entry.line() for entry in spec.ours_entries]
    print("\n".join(lines))

    entries = spec.entries()
    exported = sum(1 for entry in entries if entry.commit is not None)
    todos = [entry for entry in entries if entry.comment.startswith("TODO")]
    print(
        f"{len(entries)} Patch lines: {exported} patches written to {args.output_dir}, "
        f"{len(entries) - exported - len(todos)} already upstream, {len(todos)} TODO.",
        file=sys.stderr,
    )
    for entry in todos:
        print(f"  Patch{entry.index}: {entry.comment}", file=sys.stderr)
    if spec.title_matches:
        print("Matched upstream on their title only, worth double checking:", file=sys.stderr)
        for entry in spec.title_matches:
            print(f"  Patch{entry.index}: {entry.comment}", file=sys.stderr)
    return 0
