import argparse
import bisect
import re
import subprocess
import sys
import time
from collections import defaultdict, deque

# Every commit range in this list is searched for commits with the same title
# as an input commit.  This lets the script recognise references to either an
# upstream commit or one of its cherry-picks.  Add project-specific ranges
# here, or pass --source-range more than once on the command line.
ORIGINAL_RANGES = ["v4.19.19..master", "v4.19.19..HEAD"]
FIX_RANGE = "v4.19.19..master"
REPOSITORY = "."
MIN_HASH_SEARCH_LENGTH = 7
MAX_HASH_SEARCH_LENGTH = 12

HASH_REFERENCE_RE = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{7,40})(?![0-9a-fA-F])")
BACKPORT_HASH_RES = (
    re.compile(
        r"^\s*commit\s+([0-9a-fA-F]{7,40})\s+upstream\.?\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"^\s*\(?cherry[ -]picked from commit\s+([0-9a-fA-F]{7,40})\)?\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"^\s*\[\s*upstream commit\s+([0-9a-fA-F]{7,40})\s*\]\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
)
TITLE_TOKEN_RE = re.compile(r"\w+")
MERGE_SUBJECT_RE = re.compile(r"^Merge (?:branch(es)?|tags?)\b")


class ProgressReporter:
    """Compact stderr progress which remains readable when redirected."""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.use_color = enabled and sys.stderr.isatty()
        self.started = time.monotonic()

    def _style(self, text, color):
        if not self.use_color:
            return text

        return f"\033[{color}m{text}\033[0m"

    def step(self, number, total, message):
        if self.enabled:
            marker = self._style(f"[{number}/{total}]", "1;36")
            print(f"{marker} {message}", file=sys.stderr, flush=True)

    def detail(self, message):
        if self.enabled:
            print(f"      {message}", file=sys.stderr, flush=True)

    def progress(self, current, total, subject):
        if not self.enabled or total == 0:
            return

        interval = max(1, (total + 19) // 20)

        if current not in (1, total) and current % interval:
            return

        width = 20
        filled = width * current // total
        bar = self._style("━" * filled, "1;32") + "─" * (width - filled)
        print(
            f"      [{bar}] {current:>{len(str(total))}}/{total}  {subject}",
            file=sys.stderr,
            flush=True,
        )

    def done(self, input_count, relationship_count):
        if not self.enabled:
            return

        elapsed = time.monotonic() - self.started
        marker = self._style("Done", "1;32")
        inputs = "commit" if input_count == 1 else "commits"
        relationships = "relationship" if relationship_count == 1 else "relationships"
        print(
            f"{marker}  {input_count} {inputs}, {relationship_count} "
            f"{relationships} in {elapsed:.1f}s",
            file=sys.stderr,
            flush=True,
        )


def git(*args, check=True, input_text=None):
    return subprocess.run(
        ["git", "-C", REPOSITORY, *args],
        input=input_text,
        text=True,
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=check,
    )


def git_output(*args):
    return git(*args).stdout


def hash_search_key(commit_hash):
    """Return the conventional hash prefix used for message searches."""
    return commit_hash.lower()[:MAX_HASH_SEARCH_LENGTH]


def hashes_match(first, second):
    """Compare abbreviated hashes using no more than 12 characters."""
    first = hash_search_key(first)
    second = hash_search_key(second)
    return first.startswith(second) or second.startswith(first)


def extract_backport_hashes(body):
    """Extract upstream identities recorded by common backport markers."""
    return {
        match.group(1).lower() for pattern in BACKPORT_HASH_RES for match in pattern.finditer(body)
    }


def parse_input(lines):
    """
    Input:

        7cb2263362c7 gfs2: clean_journal improperly set sd_log_flush_head

    The supplied hash is retained as one possible identity of the commit.
    """
    commits = []

    for raw in lines:
        line = raw.strip()

        if not line or line.startswith("#"):
            continue

        parts = line.split(maxsplit=1)

        if len(parts) != 2:
            print(f"warning: cannot parse input line: {line!r}", file=sys.stderr)
            continue

        commit_hash, subject = parts

        if not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit_hash):
            print(f"warning: invalid commit hash in input line: {line!r}", file=sys.stderr)

        commits.append({"hash": commit_hash.lower(), "subject": subject})

    return commits


def load_sources(source_ranges, preloaded_range=None, preloaded_commits=()):
    """
    Load possible upstream and cherry-picked identities from source_ranges.

    Commits with the same exact subject are treated as identities of the same
    change.  Ranges are loaded separately because passing multiple A..B
    expressions to one git log command has different revision-set semantics.
    """
    by_subject = defaultdict(list)
    subjects_by_hash = {}
    seen = set()

    for source_range in source_ranges:
        if source_range == preloaded_range:
            records = ((commit["hash"], commit["subject"]) for commit in preloaded_commits)
        else:
            data = git_output("log", source_range, "--format=%H%x1f%s")
            records = (line.split("\x1f", 1) for line in data.splitlines() if "\x1f" in line)

        for commit_hash, subject in records:
            commit_hash = commit_hash.strip().lower()

            if commit_hash in seen:
                continue

            seen.add(commit_hash)
            subjects_by_hash[commit_hash] = subject
            by_subject[subject].append(
                {
                    "hash": commit_hash,
                    "subject": subject,
                }
            )

    return by_subject, subjects_by_hash


def load_commits(fix_range):
    """
    Load every commit in fix_range so both Fixes trailers and ordinary commit
    message references can be inspected.
    """
    data = git_output(
        "log",
        fix_range,
        "--format=%x1e%H%x1f%s%x1f%B",
    )

    commits = []

    for record in data.split("\x1e"):
        if not record.strip():
            continue

        fields = record.split("\x1f", 2)

        if len(fields) != 3:
            continue

        commit_hash, subject, body = fields

        commits.append(
            {
                "hash": commit_hash.strip().lower(),
                "subject": subject.strip(),
                "body": body,
                "backport_hashes": extract_backport_hashes(body),
            }
        )

    return commits


def extract_fixes_tags(body):
    """
    Parse Fixes lines.

    Typical forms:

        Fixes: 123456789abc ("some commit subject")
        Fixes: 123456789abc ("some commit subject")
        Fixes: 123456789abc

    Returns:
        [
            ("123456789abc", "some commit subject"),
            ("deadbeef1234", None),
        ]
    """
    tags = []

    for line in body.splitlines():
        match = re.match(
            r"^\s*Fixes:\s*([0-9a-fA-F]{7,40})\b"
            r'(?:.*?\(["\']?(.*?)["\']?\))?\s*$',
            line,
            re.IGNORECASE,
        )

        if not match:
            continue

        prefix = match.group(1).lower()
        subject = match.group(2)

        if subject:
            subject = subject.strip()

        tags.append((prefix, subject))

    return tags


def prefix_matches(sorted_hashes, prefix):
    """
    Return every full hash matching an abbreviated prefix.

    Uses binary search, so this does not scan the entire repository.
    """
    prefix = prefix.lower()

    lo = bisect.bisect_left(sorted_hashes, prefix)
    hi = bisect.bisect_left(sorted_hashes, prefix + "g")

    return sorted_hashes[lo:hi]


def resolve_fixes_target(
    prefix,
    tag_subject,
    fixer,
    sorted_hashes,
    subjects_by_hash,
):
    """
    Resolve a Fixes: target without silently losing ambiguous cases.

    Resolution order:

      1. Unique hash-prefix match.
      2. If ambiguous, exact subject from Fixes: tag.
      3. If still ambiguous, report it rather than silently omitting it.

    Returns a full hash or None.
    """
    matches = prefix_matches(sorted_hashes, prefix)

    if not matches:
        return None

    if len(matches) == 1:
        return matches[0]

    # A normal Linux Fixes tag includes the original commit subject.
    if tag_subject:
        subject_matches = [
            commit_hash
            for commit_hash in matches
            if subjects_by_hash.get(commit_hash) == tag_subject
        ]

        if len(subject_matches) == 1:
            return subject_matches[0]

        if subject_matches:
            matches = subject_matches

    print(
        f"warning: ambiguous Fixes target {prefix} referenced by "
        f"{fixer['hash'][:12]} {fixer['subject']}; "
        f"{len(matches)} possible commits remain",
        file=sys.stderr,
    )

    # Do not guess and introduce false Fixes relationships.
    return None


def build_fixes_graph(commits, sorted_hashes, subjects_by_hash):
    """
    Build:

        fixed commit -> commits which Fixes: it
    """
    graph = defaultdict(list)

    for fixer in commits:
        for prefix, tag_subject in extract_fixes_tags(fixer["body"]):
            target = resolve_fixes_target(
                prefix,
                tag_subject,
                fixer,
                sorted_hashes,
                subjects_by_hash,
            )

            if target is None:
                continue

            graph[target].append(fixer)

    return graph


def resolve_input_hashes(commit_hashes):
    """Resolve input hashes with a single cat-file batch process."""
    commit_hashes = list(
        dict.fromkeys(
            commit_hash.lower()
            for commit_hash in commit_hashes
            if re.fullmatch(r"[0-9a-fA-F]{7,40}", commit_hash)
        )
    )

    if not commit_hashes:
        return {}

    requests = "".join(f"{commit_hash}^{{commit}}\n" for commit_hash in commit_hashes)
    result = git(
        "cat-file",
        "--batch-check=%(objectname) %(objecttype)",
        input_text=requests,
        check=False,
    )

    if result.returncode != 0:
        return {}

    resolved = {}

    for commit_hash, line in zip(commit_hashes, result.stdout.splitlines(), strict=False):
        fields = line.split()

        if len(fields) != 2 or fields[1] != "commit":
            continue

        object_hash = fields[0].lower()

        if re.fullmatch(r"[0-9a-f]{40}", object_hash):
            resolved[commit_hash] = object_hash

    return resolved


def load_backport_hashes(commit_hashes):
    """Load backport markers for many commits with one Git process."""
    commit_hashes = list(dict.fromkeys(commit_hashes))

    if not commit_hashes:
        return {}

    result = git(
        "show",
        "--no-patch",
        "--format=%x1e%H%x1f%B",
        *commit_hashes,
        check=False,
    )

    if result.returncode != 0:
        return {}

    hashes_by_commit = {}

    for record in result.stdout.split("\x1e"):
        if "\x1f" not in record:
            continue

        commit_hash, body = record.split("\x1f", 1)
        hashes_by_commit[commit_hash.strip().lower()] = extract_backport_hashes(body)

    return hashes_by_commit


def original_identities(input_commit, sources_by_subject):
    """Return all known hashes for an input change."""
    hashes = {source["hash"] for source in sources_by_subject.get(input_commit["subject"], [])}

    resolved_input = input_commit.get("resolved_hash")

    if resolved_input:
        hashes.add(resolved_input)

    return hashes


def normalize_whitespace(text):
    """Collapse spaces, tabs, indentation, and line breaks to one space."""
    return " ".join(text.split())


def build_mention_index(commits, subjects):
    """Index commit messages once for fast title and hash lookups."""
    relevant_tokens = {
        token
        for subject in subjects
        for token in TITLE_TOKEN_RE.findall(normalize_whitespace(subject))
    }
    title_token_commits = defaultdict(list)
    hash_reference_commits = defaultdict(list)

    for position, commit in enumerate(commits):
        body = commit.pop("body")
        normalized_body = normalize_whitespace(body)
        references = {hash_search_key(match.group(1)) for match in HASH_REFERENCE_RE.finditer(body)}
        commit["normalized_body"] = normalized_body
        commit["hash_references"] = references

        for token in set(TITLE_TOKEN_RE.findall(normalized_body)) & relevant_tokens:
            title_token_commits[token].append(position)

        for reference in references:
            hash_reference_commits[reference].append(position)

    return {
        "title_tokens": title_token_commits,
        "hash_references": hash_reference_commits,
        "sorted_hash_references": sorted(hash_reference_commits),
    }


def find_mentions(
    subject,
    hash_aliases,
    target_hashes,
    commits,
    mention_index,
    excluded_hashes,
):
    """Find later commits which mention a target title or hash identity."""
    results = []
    normalized_subject = normalize_whitespace(subject)
    subject_tokens = set(TITLE_TOKEN_RE.findall(normalized_subject))
    candidate_positions = set()

    if subject_tokens:
        postings = [mention_index["title_tokens"].get(token, ()) for token in subject_tokens]

        if all(postings):
            postings.sort(key=len)
            title_positions = set(postings[0])

            for other_postings in postings[1:]:
                title_positions.intersection_update(other_postings)

            candidate_positions.update(title_positions)
    else:
        candidate_positions.update(range(len(commits)))

    for alias in hash_aliases:
        alias = hash_search_key(alias)
        sorted_references = mention_index["sorted_hash_references"]
        first = bisect.bisect_left(sorted_references, alias)
        last = bisect.bisect_left(sorted_references, alias + "g")

        for reference in sorted_references[first:last]:
            candidate_positions.update(mention_index["hash_references"][reference])

        for length in range(MIN_HASH_SEARCH_LENGTH, len(alias) + 1):
            candidate_positions.update(mention_index["hash_references"].get(alias[:length], ()))

    for position in sorted(candidate_positions):
        commit = commits[position]
        commit_hash = commit["hash"]

        if commit_hash in target_hashes or commit_hash in excluded_hashes:
            continue

        mentions_title = normalized_subject in commit["normalized_body"]
        matching_references = {
            reference
            for reference in commit["hash_references"]
            if any(hashes_match(alias, reference) for alias in hash_aliases)
        }

        if not mentions_title and not matching_references:
            continue

        if matching_references:
            matched_as = max(matching_references, key=lambda reference: (len(reference), reference))
        else:
            matched_as = "title"

        results.append((commit, matched_as))

    return results


def find_recursive_relationships(
    input_commit,
    source_hashes,
    sources_by_subject,
    fixes_graph,
    commits,
    mention_index,
):
    """
    Find fixes and mentions recursively.

    Every result becomes another target, so this finds fixes-of-fixes,
    mentions-of-fixes, fixes-of-mentions, and mentions-of-mentions.
    """
    children_by_parent = defaultdict(list)
    root_aliases = set(source_hashes)
    root_aliases.add(input_commit["hash"])
    root_aliases.update(input_commit.get("backport_hashes", ()))
    queue = deque(
        [
            (
                input_commit["subject"],
                set(source_hashes),
                root_aliases,
                None,
            )
        ]
    )
    visited = set(source_hashes)

    while queue:
        subject, target_hashes, hash_aliases, parent_hash = queue.popleft()
        fixed = []
        fixed_hashes = set()

        for target_hash in sorted(target_hashes):
            for fixer in fixes_graph.get(target_hash, []):
                fixer_hash = fixer["hash"]

                if fixer_hash in visited or fixer_hash in fixed_hashes:
                    continue

                fixed.append(fixer)
                fixed_hashes.add(fixer_hash)

        mentioned = find_mentions(
            subject,
            hash_aliases,
            target_hashes,
            commits,
            mention_index,
            visited | fixed_hashes,
        )

        for relationship, related_commits in (
            ("Fixed-by", ((commit, None) for commit in fixed)),
            ("Mentioned-by", mentioned),
        ):
            for commit, matched_as in related_commits:
                commit_hash = commit["hash"]

                if commit_hash in visited:
                    continue

                visited.add(commit_hash)
                children_by_parent[parent_hash].append((relationship, commit, matched_as))

                identities = {
                    source["hash"] for source in sources_by_subject.get(commit["subject"], [])
                }
                identities.add(commit_hash)
                aliases = set(identities)
                aliases.update(commit.get("backport_hashes", ()))

                queue.append(
                    (
                        commit["subject"],
                        identities,
                        aliases,
                        commit_hash,
                    )
                )

    # Discovery above is breadth-first so a direct/shorter relationship wins
    # when a commit is reachable through multiple paths. Render the recorded
    # parent tree depth-first so children appear beneath their actual parent.
    results = []
    stack = [
        (1, relationship, commit, matched_as)
        for relationship, commit, matched_as in reversed(children_by_parent[None])
    ]

    while stack:
        depth, relationship, commit, matched_as = stack.pop()
        results.append((depth, relationship, commit, matched_as))
        stack.extend(
            (depth + 1, child_relationship, child, child_matched_as)
            for child_relationship, child, child_matched_as in reversed(
                children_by_parent[commit["hash"]]
            )
        )

    return results


def prune_merge_only_subtrees(relationships):
    """Remove subtrees made up solely of merge-commit mentions."""
    keep = [False] * len(relationships)
    processed_subtrees = []

    for position in range(len(relationships) - 1, -1, -1):
        depth, relationship, commit, _ = relationships[position]
        has_retained_child = False

        while processed_subtrees and processed_subtrees[-1][0] > depth:
            _, retained = processed_subtrees.pop()
            has_retained_child = has_retained_child or retained

        is_merge_mention = relationship == "Mentioned-by" and bool(
            MERGE_SUBJECT_RE.match(commit["subject"])
        )
        keep[position] = not is_merge_mention or has_retained_child
        processed_subtrees.append((depth, keep[position]))

    return [relationship for position, relationship in enumerate(relationships) if keep[position]]


def main():
    global REPOSITORY

    parser = argparse.ArgumentParser(
        description=(
            "Locate all identities of each input commit by exact subject, "
            "then find later Fixes: commits and commit-message mentions."
        )
    )

    parser.add_argument(
        "file",
        nargs="?",
        help="input file; omit or use - for stdin",
    )

    parser.add_argument(
        "-C",
        "--repo",
        default=REPOSITORY,
        metavar="PATH",
        help="repository to inspect (default: current directory)",
    )

    parser.add_argument(
        "--source-range",
        dest="source_ranges",
        action="append",
        metavar="RANGE",
        help=(
            "range used to identify upstream/cherry-picked instances; "
            "repeat for multiple ranges (default: "
            f"{', '.join(ORIGINAL_RANGES)})"
        ),
    )

    parser.add_argument(
        "--fix-range",
        default=FIX_RANGE,
        metavar="RANGE",
        help=f"range searched for later commits (default: {FIX_RANGE})",
    )

    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress progress output on stderr",
    )

    args = parser.parse_args()
    REPOSITORY = args.repo

    if git("rev-parse", "--git-dir", check=False).returncode != 0:
        parser.error(f"cannot access Git repository: {REPOSITORY}")

    source_ranges = args.source_ranges or ORIGINAL_RANGES
    fix_range = args.fix_range
    progress = ProgressReporter(enabled=not args.quiet)

    progress.step(1, 6, "Read input commits")
    if args.file and args.file != "-":
        with open(args.file, encoding="utf-8") as f:
            input_commits = parse_input(f)
    else:
        input_commits = parse_input(sys.stdin)
    progress.detail(
        f"{len(input_commits)} commit{'s' if len(input_commits) != 1 else ''} requested"
    )

    progress.step(2, 6, f"Load candidate commits from {fix_range}")
    commits = load_commits(fix_range)
    progress.detail(f"{len(commits)} candidate commit{'s' if len(commits) != 1 else ''} loaded")

    range_label = "source range" if len(source_ranges) == 1 else "source ranges"
    progress.step(3, 6, f"Load identities from {len(source_ranges)} {range_label}")
    sources_by_subject, subjects_by_hash = load_sources(
        source_ranges,
        preloaded_range=fix_range,
        preloaded_commits=commits,
    )
    progress.detail(f"{len(subjects_by_hash)} unique commit identities loaded")

    for commit in commits:
        subjects_by_hash.setdefault(commit["hash"], commit["subject"])

    indexed_hashes = sorted(subjects_by_hash)

    # An explicitly supplied commit can sit just outside all configured
    # ranges.  Include it in Fixes-prefix resolution when Git knows it.
    progress.step(4, 6, "Resolve input and backport identities")
    unresolved_input_hashes = []

    for input_commit in input_commits:
        indexed_matches = prefix_matches(indexed_hashes, input_commit["hash"])

        if len(indexed_matches) == 1:
            input_commit["resolved_hash"] = indexed_matches[0]
        else:
            input_commit["resolved_hash"] = None
            unresolved_input_hashes.append(input_commit["hash"])

    resolved_input_hashes = resolve_input_hashes(unresolved_input_hashes)

    for input_commit in input_commits:
        if input_commit["resolved_hash"] is None:
            input_commit["resolved_hash"] = resolved_input_hashes.get(input_commit["hash"])

    backport_hashes_by_commit = load_backport_hashes(
        input_commit["resolved_hash"]
        for input_commit in input_commits
        if input_commit["resolved_hash"]
    )

    for input_commit in input_commits:
        resolved_input = input_commit["resolved_hash"]
        input_commit["backport_hashes"] = backport_hashes_by_commit.get(resolved_input, set())

        if resolved_input:
            subjects_by_hash.setdefault(
                resolved_input,
                input_commit["subject"],
            )

    resolved_count = sum(
        input_commit["resolved_hash"] is not None for input_commit in input_commits
    )
    alias_count = sum(len(input_commit["backport_hashes"]) for input_commit in input_commits)
    progress.detail(
        f"{resolved_count}/{len(input_commits)} inputs resolved; "
        f"{alias_count} backport aliases found"
    )

    progress.step(5, 6, "Build fixes and mention indexes")
    sorted_hashes = sorted(subjects_by_hash)
    graph = build_fixes_graph(commits, sorted_hashes, subjects_by_hash)
    mention_index = build_mention_index(
        commits,
        {
            *sources_by_subject,
            *(commit["subject"] for commit in commits),
            *(input_commit["subject"] for input_commit in input_commits),
        },
    )
    fixes_count = sum(len(fixers) for fixers in graph.values())
    hash_reference_count = len(mention_index["hash_references"])
    progress.detail(
        f"{fixes_count} Fixes relationships; {hash_reference_count} hash references indexed"
    )

    progress.step(6, 6, "Find recursive relationships")
    relationship_count = 0

    for position, input_commit in enumerate(input_commits, 1):
        subject = input_commit["subject"]
        progress.progress(position, len(input_commits), subject)
        source_hashes = original_identities(
            input_commit,
            sources_by_subject,
        )

        if not source_hashes:
            print(subject)
            print(f"  Error: original commit not found in {', '.join(source_ranges)}")
            continue

        relationships = find_recursive_relationships(
            input_commit,
            source_hashes,
            sources_by_subject,
            graph,
            commits,
            mention_index,
        )
        relationships = prune_merge_only_subtrees(relationships)
        relationship_count += len(relationships)

        if not relationships:
            continue

        print(subject)

        for depth, relationship, commit, matched_as in relationships:
            indent = "  " * depth
            suffix = f" (as {matched_as})" if matched_as else ""

            print(f"{indent}{relationship}: {commit['hash'][:12]} {commit['subject']}{suffix}")

    progress.done(len(input_commits), relationship_count)


if __name__ == "__main__":
    main()
