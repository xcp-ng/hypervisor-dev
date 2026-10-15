# commit-graph-tools

Utilities for finding follow-up fixes and references to Git commits, and checking
which of those related commits have been backported to another branch.

- `find-fixers-recursive` follows `Fixes:` trailers and commit-message mentions
  recursively, including fixes of fixes and references to those fixes.
- `find-applied-fixes-recursive` filters that output to show related commits
  already present in a target revision range, or missing from it.

Both commands inspect an existing Git repository without changing its checkout.

## Workflow

Run the following from the Git repository containing the relevant histories,
with both commands installed and available on `PATH`. The defaults target a
Linux kernel repository with the `v4.19.19` tag and a `master` branch:

```sh
git log --reverse --format='%h %s' \
  xcpng/kernel/xcpng-4.19.19-8.0.46.10/patched..xcpng/kernel/xcpng-4.19.19-8.0.46.10/patched-cves-nebusec \
  > commits.txt
find-fixers-recursive commits.txt > fixes.txt
find-applied-fixes-recursive --missing fixes.txt > missing.txt
```

`fixes.txt` contains the recursive relationships found upstream. `missing.txt`
contains related commits whose subjects are absent from `v4.19.19..HEAD`.
Drop `--missing` to show those already present; add `--show-local-hash` to display
the matching local hashes.

The commands also accept stdin, so the same workflow can be piped:

```sh
git log --reverse --format='%h %s' \
  xcpng/kernel/xcpng-4.19.19-8.0.46.10/patched..xcpng/kernel/xcpng-4.19.19-8.0.46.10/patched-cves-nebusec \
  | find-fixers-recursive \
  | find-applied-fixes-recursive --missing
```

For other repositories or branch layouts, set the ranges explicitly. For
example, given a shared `base` tag, an `upstream` branch and a `downstream` branch:

```sh
git -C /path/to/repo log --reverse --format='%h %s' base..downstream \
  | find-fixers-recursive -C /path/to/repo \
      --source-range base..upstream \
      --source-range base..downstream \
      --fix-range base..upstream \
  | find-applied-fixes-recursive -C /path/to/repo \
      --tree-range base..downstream --missing
```

All referenced commits and ranges must be available in the selected repository.
As with Git, `base..branch` excludes commits reachable from `base`, including
`base` itself. Each command selects its repository independently; pass `-C` to
both when piping commands outside that repository.

## Finding related commits

```text
find-fixers-recursive [OPTIONS] [FILE]
```

Input must contain one commit per line: a 7–40 character hexadecimal hash,
whitespace, then the commit subject. Generate it with
`git log --format='%h %s'`; the default `git log` format is unsuitable. Blank
lines and lines starting with `#` are ignored. Omit `FILE` or use `-` for stdin.

| Option | Purpose | Default |
| --- | --- | --- |
| `-C PATH`, `--repo PATH` | Repository to inspect | Current directory |
| `--source-range RANGE` | Identify upstream and cherry-picked copies by exact subject; repeat for multiple ranges | `v4.19.19..master` and `v4.19.19..HEAD` |
| `--fix-range RANGE` | Search this range for fixes and mentions | `v4.19.19..master` |
| `--quiet` | Suppress progress on stderr | Progress enabled |

Supplying any `--source-range` replaces the default source ranges. Source ranges
identify copies of a change; `--fix-range` determines which commits can appear
as follow-up results. An input hash that Git can resolve is also considered even
when it falls outside the source ranges.

Output groups relationships beneath the input subject, with two spaces per
recursion level. For example:

```text
Original change
  Fixed-by: aaaaaaaaaaaa Fix original change
    Mentioned-by: bbbbbbbbbbbb Discuss the fix (as aaaaaaaaaaaa)
      Fixed-by: cccccccccccc Fix the follow-up
  Mentioned-by: dddddddddddd Discuss original change (as title)
```

- `Fixed-by` means a `Fixes:` trailer resolves to a known identity of the target
  commit. Ambiguous hash prefixes are checked against the trailer's subject;
  unresolved ambiguity produces a warning and the link is skipped.
- `Mentioned-by` means a commit message contains the target subject or a hash
  reference. `(as title)` indicates a subject match; `(as HASH)` shows the
  matching hash reference. Subject searches collapse whitespace and are case
  sensitive. Hash searches accept references of at least seven characters and
  compare at most the first twelve characters.

The search recognizes upstream aliases from `commit HASH upstream`,
`(cherry picked from commit HASH)` and `[ Upstream commit HASH ]` markers.
Every discovered result becomes another search target. Each related commit
appears once per input, with a shorter relationship path taking precedence.
Subtrees consisting solely of mentions by commits with generic merge subjects
are omitted.

Inputs with no relationships are omitted. If neither a matching source subject
nor a resolvable input hash is found, the output includes the input subject and
an indented `Error:` line. Progress and warnings go to stderr, leaving stdout
available for files and pipelines; `--quiet` suppresses progress only.

## Checking applied fixes

```text
find-applied-fixes-recursive [OPTIONS] [FILE]
```

Reads the grouped output of `find-fixers-recursive` from `FILE` or stdin
(`FILE` omitted or `-`). Both `Fixed-by` and `Mentioned-by` entries are checked.

| Option | Purpose | Default |
| --- | --- | --- |
| `-C PATH`, `--repo PATH` | Repository to inspect | Current directory |
| `--tree-range RANGE` | Revision range checked for matching subjects | `v4.19.19..HEAD` |
| `--missing` | Show related commits absent from the range | Show present commits |
| `--show-local-hash` | Append matching local hashes to present entries | Disabled |

Matching uses **exact commit subjects**, without comparing patches or checking
ancestry against the upstream hashes. A changed backport subject can therefore
look missing, and an unrelated commit with the same subject can look present.
Likewise, discovery treats identical non-merge subjects as copies of a change,
and ordinary message mentions do not necessarily identify fixes. Review the
results before deciding what to backport.

Filtering preserves relationship labels, annotations and original indentation.
A child can remain even when its parent is filtered out. Groups without retained
entries are omitted, and `Error:` lines from discovery are ignored. A count of
present or missing relationship entries is written to stderr. Missing commits
do not cause a nonzero exit status.

## Development

From `scripts/commit-graph-tools`, install the development dependencies and run
the existing checks:

```sh
uv sync --group dev
uv run pytest
uv run ruff check .
uv run pyright
```
