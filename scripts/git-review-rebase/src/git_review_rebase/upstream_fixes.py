"""Index of the upstream commits fixing other commits, from their Fixes: tags."""

import pygit2

from .git_utils import commit_title, fixes_references, git_log_messages

# Shortest sha1 prefix accepted in a Fixes: tag, and length of the titles compared.
MIN_SHA1_PREFIX_LENGTH = 7
TITLE_LENGTH = 60


class MissingFix:
    """Upstream fix which was not backported, along with the commit it fixes.

    The fixed commit is either the cherry-picked commit (depth 0), or another fix of it."""

    def __init__(self, commit: pygit2.Commit, fixed_commit: pygit2.Commit, depth: int):
        self.commit = commit
        self.fixed_commit = fixed_commit
        self.depth = depth


class UpstreamFixes:
    """Upstream commits carrying a Fixes: tag, by referenced sha1 prefix and title.

    Built from a single git log over the whole upstream range, as running one git log per commit
    is much slower as soon as there are more than a handful of commits to look up."""

    def __init__(self, repo: pygit2.Repository, revisions: list[str], paths: list[str]):
        self.repo = repo
        self.fixes_by_sha1_prefix: dict[str, list[str]] = {}
        self.fixes_by_title: dict[str, list[str]] = {}
        # Oldest first, i.e. in the order they should be backported.
        commits = reversed(git_log_messages(repo, revisions, paths, grep=r"^[[:space:]]*Fixes:"))
        for fix_sha1, message in commits:
            for sha1_prefix, title in fixes_references(message):
                self.fixes_by_sha1_prefix.setdefault(sha1_prefix, []).append(fix_sha1)
                if title:
                    self.fixes_by_title.setdefault(title[:TITLE_LENGTH], []).append(fix_sha1)

    def fixes_of(self, commit: pygit2.Commit) -> list[pygit2.Commit]:
        """Return the commits fixing the given one, oldest first.

        Fixes: tags are matched on the sha1 prefix, or on the title when the sha1 is wrong."""
        sha1 = str(commit.id)
        fix_sha1s: list[str] = []
        for length in range(MIN_SHA1_PREFIX_LENGTH, len(sha1) + 1):
            fix_sha1s += self.fixes_by_sha1_prefix.get(sha1[:length], [])
        fix_sha1s += self.fixes_by_title.get(commit_title(commit)[:TITLE_LENGTH], [])

        fixes: list[pygit2.Commit] = []
        # Deduplicate while keeping the order.
        for fix_sha1 in dict.fromkeys(fix_sha1s):
            fix = self.repo.get(fix_sha1)
            assert isinstance(fix, pygit2.Commit)
            fixes.append(fix)
        return fixes
