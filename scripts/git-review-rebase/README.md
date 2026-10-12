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

This installs both the `git-review-rebase` and `git-review-backports` commands.

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

A modified backport gets `⇅` when it was applied in a different order than upstream relative to
another backport touching the same functions (taken from the diff hunk headers), as reordering
them may give cleaner backports. Pairs of clean backports are ignored. When such a backport is
highlighted, the commits it was reordered with are highlighted too.

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
