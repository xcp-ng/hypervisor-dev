"""Commit matching logic for reviewing backports against their upstream commits."""

import argparse
from collections import OrderedDict
from itertools import combinations

import pygit2

from .commit_matching import RebasedCommitMatch
from .constants import CacheFlags, CommitMatchInfoFlag
from .git_utils import cherry_pick_parents, commit_touches_paths, oid, patchid, range_log


def upstream_commit(repo: pygit2.Repository, commit: pygit2.Commit) -> None | pygit2.Commit:
    """Return the last cherry-picked commit referenced in the message and present in the repo."""
    for sha1 in reversed(cherry_pick_parents(commit)):
        upstream = repo.get(sha1)
        if isinstance(upstream, pygit2.Commit):
            return upstream
    return None


ChangedBlobs = dict[str, tuple[None | pygit2.Oid, None | pygit2.Oid]]

# Stands for every function of an added or removed file. Hunks outside of any function have an
# empty header, and only overlap with each other.
WHOLE_FILE = "\0"


def _changed_blobs(old: None | pygit2.Tree, new: None | pygit2.Tree, prefix: str) -> ChangedBlobs:
    old_entries = {entry.name: entry for entry in old} if old is not None else {}
    new_entries = {entry.name: entry for entry in new} if new is not None else {}
    changed: ChangedBlobs = {}
    for name in old_entries.keys() | new_entries.keys():
        o, n = old_entries.get(name), new_entries.get(name)
        if o is not None and n is not None and o.id == n.id:
            continue
        path = f"{prefix}{name}"
        o_tree = o if isinstance(o, pygit2.Tree) else None
        n_tree = n if isinstance(n, pygit2.Tree) else None
        if o_tree is not None or n_tree is not None:
            changed.update(_changed_blobs(o_tree, n_tree, f"{path}/"))
        o_blob = o.id if o is not None and o_tree is None else None
        n_blob = n.id if n is not None and n_tree is None else None
        if o_blob is not None or n_blob is not None:
            changed[path] = (o_blob, n_blob)
    return changed


def changed_blobs(commit: pygit2.Commit) -> ChangedBlobs:
    """Return the (old, new) blob ids of each path modified by the commit.

    Only descends into modified subtrees, which is much faster than a libgit2 tree diff."""
    if not commit.parents:
        return {}
    return _changed_blobs(commit.parents[0].tree, commit.tree, "")


def touched_functions(
    repo: pygit2.Repository, path: str, old: None | pygit2.Oid, new: None | pygit2.Oid
) -> set[str]:
    """Return the functions modified in a file, from the hunk headers of its diff."""
    old_blob, new_blob = repo.get(old) if old else None, repo.get(new) if new else None
    if not isinstance(old_blob, pygit2.Blob) or not isinstance(new_blob, pygit2.Blob):
        return {WHOLE_FILE}
    patch = old_blob.diff(new_blob, old_as_path=path, new_as_path=path)
    # "@@ -1,2 +1,3 @@ function context"
    return {hunk.header.split("@@", 2)[-1].strip() for hunk in patch.hunks}


class BackportMatches:
    """Match each commit of a range with the upstream commit it was cherry-picked from."""

    def __init__(
        self,
        args: argparse.Namespace,
        repo: pygit2.Repository,
        start_range: str,
        end_range: str,
        cache_flags: CacheFlags,
    ):
        self.args = args
        self.repo = repo
        self.cache_flags = cache_flags
        self.commit_matches: OrderedDict[pygit2.Oid, RebasedCommitMatch] = OrderedDict()
        # Backports applied in a different order than upstream and touching the same functions,
        # by backport commit id. Symmetric, even though only modified backports are flagged.
        self.out_of_order: dict[pygit2.Oid, set[pygit2.Oid]] = {}
        self.init_matches(oid(repo, start_range), oid(repo, end_range))
        self.init_out_of_order()

    def init_matches(self, start: pygit2.Oid, end: pygit2.Oid) -> None:
        for backport in range_log(self.repo, start, end):
            if not commit_touches_paths(backport, self.args.paths):
                continue

            upstream = upstream_commit(self.repo, backport)
            if upstream is not None:
                if patchid(self.repo, upstream, self.cache_flags) == patchid(
                    self.repo, backport, self.cache_flags
                ):
                    match_info = CommitMatchInfoFlag.CleanBackport
                else:
                    match_info = CommitMatchInfoFlag.ModifiedBackport
            elif cherry_pick_parents(backport):
                match_info = CommitMatchInfoFlag.UpstreamNotFound
            else:
                match_info = CommitMatchInfoFlag.NoCherryPickReference

            self.commit_matches[backport.id] = RebasedCommitMatch(upstream, backport, match_info)

    def init_out_of_order(self) -> None:
        # Oldest first, i.e. in the order the backports were applied.
        applied = [m for m in reversed(self.commit_matches.values()) if m.left_commit is not None]
        if not any(CommitMatchInfoFlag.ModifiedBackport in m.match_info for m in applied):
            return

        blobs: dict[pygit2.Oid, ChangedBlobs] = {}
        functions: dict[tuple[pygit2.Oid, str], set[str]] = {}

        def file_functions(c: pygit2.Commit, path: str) -> set[str]:
            if (c.id, path) not in functions:
                functions[c.id, path] = touched_functions(self.repo, path, *blobs[c.id][path])
            return functions[c.id, path]

        def overlap(a: pygit2.Commit, b: pygit2.Commit) -> bool:
            for c in (a, b):
                if c.id not in blobs:
                    blobs[c.id] = changed_blobs(c)
            for path in blobs[a.id].keys() & blobs[b.id].keys():
                a_functions, b_functions = file_functions(a, path), file_functions(b, path)
                if WHOLE_FILE in a_functions | b_functions or a_functions & b_functions:
                    return True
            return False

        for first, second in combinations(applied, 2):
            # Identical patch-ids on both sides: the order did not matter.
            if (
                CommitMatchInfoFlag.ModifiedBackport not in first.match_info
                and CommitMatchInfoFlag.ModifiedBackport not in second.match_info
            ):
                continue
            assert first.left_commit is not None and second.left_commit is not None
            assert first.right_commit is not None and second.right_commit is not None
            if not overlap(first.left_commit, second.left_commit):
                continue
            # Applied first, but comes after upstream. Comparing commit dates first avoids most of
            # the (slow) ancestry walks, as a commit cannot descend from a more recent one.
            if first.left_commit.commit_time < second.left_commit.commit_time:
                continue
            if not self.repo.descendant_of(first.left_commit.id, second.left_commit.id):
                continue

            self.out_of_order.setdefault(first.right_commit.id, set()).add(second.right_commit.id)
            self.out_of_order.setdefault(second.right_commit.id, set()).add(first.right_commit.id)
            for match in (first, second):
                if CommitMatchInfoFlag.ModifiedBackport in match.match_info:
                    match.match_info |= CommitMatchInfoFlag.OutOfOrder
