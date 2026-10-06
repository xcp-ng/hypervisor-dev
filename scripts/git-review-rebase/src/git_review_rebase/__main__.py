"""Entry points for git-review-rebase and git-review-backports."""

from .app import GitReviewRebase
from .cli import parse_args, parse_backports_args


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


if __name__ == "__main__":
    main()
