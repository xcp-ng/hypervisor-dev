# git-review-rebase

An interactive TUI (Terminal User Interface) tool for reviewing rebased git branches side-by-side.

![git-review-rebase demo](imgs/git-review-rebase-demo.gif)

## Features

- Side-by-side diff viewing for rebased commits
- Interactive commit matching between branches
- Syntax highlighting with token-level diff highlighting
- Git blame integration for tracking commit origins
- Fuzzy search across commits
- Flexible filtering by commit match types
- Possibility to add notes to dropped commits

### Commit match icons

  | Icon | Meaning                                   |
  | ---- | ----------------------------------------- |
  | `=`  | Same commit (identical SHA1               |
  | `~`  | Loose match (same title, patchid changed) |
  | `✎`  | Commit message changed                    |
  | `⤶`  | Already present in new upstream           |
  | `✗`  | Dropped during rebase                     |
  | `✚`  | Added in rebase                           |

> A commit message comparison ignores trailing whitespace and surrounding blank lines, so `✎`
> only shows up when the message content itself differs. It is never set on `=` matches, since
> those commits are identical by definition.

> **Patchid** is a checksum of a commit's diff (`git patch-id`). Two commits with different
> SHA1 (e.g. after rebase) that introduce the same code changes will have the same patchid.
> This allows the tool to match commits across a rebase even when their SHA-1s change.

## Installation

### From source

```bash
pip install -e .
```

This installs the `git-review-rebase`, `git-review-backports` and `git-spec-patches` commands.

## Usage

```bash
git-review-rebase <base>..<left-branch> <onto_base>..<right-branch>
```

### Options

- `--repository PATH`: Path to git repository (default: current directory)
- `--no-cache`: Disable patchid caching

### Reviewing backports

```bash
git-review-backports <base>..<branch> [PATH...]
```

`git-review-backports` uses the same UI to review a range of backported commits. Each commit is
shown next to the upstream commit it was cherry-picked from: the last one referenced in its
message, using any of the `(cherry picked from commit <sha1>)`, `commit <sha1> upstream` or
`[ Upstream commit <sha1> ]` formats. Pressing `p` lets you pick another referenced commit.

  | Icon | Meaning                                          |
  | ---- | ------------------------------------------------ |
  | `=`  | Clean backport (same patchid as upstream)        |
  | `~`  | Modified backport (patchid differs)              |
  | `?`  | Cherry-picked commit not found in the repository |
  | `✗`  | No cherry-picked commit in the message           |
  | `⇅`  | Modified backport applied out of upstream order  |
  | `!`  | Upstream fixes missing from the backports        |

A modified backport gets `⇅` when it was applied in a different order than upstream relative to
another backport touching the same functions (taken from the diff hunk headers), as reordering
them may give cleaner backports. Pairs of clean backports are ignored. When such a backport is
highlighted, the commits it was reordered with are highlighted too.

#### Missing upstream fixes

```bash
git-review-backports --upstream origin/master <base>..<branch> [PATH...]
```

With `--upstream`, a backport gets `!` when its upstream commit is referenced by a `Fixes:` tag
(by sha1 prefix, or by its first 60 title characters) of a commit in `<branch>..<upstream>` which
was not backported. A fix counts as backported when a commit in `<branch> ^<upstream>` references
it in a cherry-pick line or has the same title. Pressing `x` lists the missing fixes, and
selecting one shows its diff.

The fixes are searched in a single `git log` limited to the given paths or, without paths, to the
directories touched by the upstream commits. It is meant for short lists of backports touching
the same subsystems, and is much faster with changed-path Bloom filters:

```bash
git commit-graph write --reachable --changed-paths
```

Fixes of fixes are searched recursively, including the fixes of backported fixes, and listed
indented under the commit they fix. The fixes of a commit backported in the reviewed range are
only listed on its own row.

## Generating spec file patches

```bash
git-spec-patches -o <SOURCES> [--remote vates] [--end-xenserver-patchqueue <commit>] \
    [--ours-start 1000] <base>..<imported-branch> <onto_base>..<rebased-branch>
```

`git-spec-patches` turns a rebased patch-queue back into the `PatchN` lines of a SRPM spec file,
and writes their patch files to the output directory, typically the `SOURCES/` directory of the
SRPM repository after removing its old patches. The left range is the patch-queue imported from
the SRPM by `git-import-srpm`, whose commits are in the order of the `Patch` lines starting at
`Patch0`. The right range is that patch-queue rebased on its new base. Commits are matched like in
`git-review-rebase`, and each left commit keeps its index:

  | Left commit                     | Spec line                                       |
  | ------------------------------- | ----------------------------------------------- |
  | Rebased                         | `Patch42: 0042-<title>.patch`, re-exported      |
  | Already present in the new base | `# Patch42: <upstream sha1> ("<upstream title>")` |
  | Dropped                         | `# Patch42: TODO ("<title>")`, to be filled in  |

The left commits up to the end of the XenServer patch-queue form the XenServer block, and keep
their XenServer index, so that the generated lines can be diffed with the XenServer spec file. The
end of the XenServer patch-queue is, in order of preference:

1. the commit given with `--end-xenserver-patchqueue`, which must be in the left range,
2. the tip of the XenServer branch the imported branch is based on, found on `--remote`: e.g.
   `vates/kernel/xenserver-4.19.19-8.0.46/patched` for `kernel/xcpng-4.19.19-8.0.46.17/patched`,
3. the last `abi-version` commit of the left range, with a warning,
4. the end of the left range, with a warning.

The following left commits, and the commits only present on the right, form our own block,
numbered from `--ours-start` in the order they are applied on the right. Commits only present on
the right must come after the XenServer block, and the rebased commits must keep their order: the
tool refuses to generate anything otherwise.

The `Patch` lines are printed on the standard output, and a summary listing the `TODO` lines and
the commits matched upstream on their title only, which are worth double checking, on the
standard error. Patches are generated with `git format-patch` regardless of the user's
configuration, and existing files are never overwritten. Once the spec file is updated, importing
the SRPM with `git-import-srpm` should give the same commits as the rebased branch, except for
commits whose message does not start with a single title line: `git am` joins their first
paragraph into one title line.

## Development

### Setup

```bash
# Install in development mode with dev dependencies
pip install -e ".[dev]"
```

### Code formatting and linting

```bash
black src/
ruff check src/
flake8 src/
```

### Type checking

```bash
mypy src/
pyright ./
```

## License

GPL-v2

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
