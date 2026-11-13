"""Entry points for git-review-rebase, git-review-backports and git-spec-patches."""

import sys

from .app import GitReviewRebase
from .cli import parse_args, parse_backports_args, parse_spec_patches_args
from .spec_patches import main as spec_patches_main


def main():
    """git-review-rebase entry point."""
    args = parse_args()
    app = GitReviewRebase(args)
    app.run()


def main_backports():
    """git-review-backports entry point."""
    args = parse_backports_args()
    app = GitReviewRebase(args)
    app.run()


def main_spec_patches():
    """git-spec-patches entry point."""
    sys.exit(spec_patches_main(parse_spec_patches_args()))


if __name__ == "__main__":
    main()
