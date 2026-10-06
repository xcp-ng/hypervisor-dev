"""Commit matching logic for reviewing backports against their upstream commits."""

import argparse
from collections import OrderedDict

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
        self.init_matches(oid(repo, start_range), oid(repo, end_range))

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
