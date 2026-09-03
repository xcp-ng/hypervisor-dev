import io
import subprocess
import sys
import tempfile
from pathlib import Path

from commit_graph_tools import find_applied_fixes_recursive

MODULE = "commit_graph_tools.find_applied_fixes_recursive"


def run(command, *, cwd=None, input_text=None, check=True):
    return subprocess.run(
        [str(argument) for argument in command],
        cwd=cwd,
        input=input_text,
        text=True,
        capture_output=True,
        check=check,
    )


def git(repo, *args):
    return run(["git", "-C", repo, *args]).stdout.strip()


def commit(repo, subject):
    git(repo, "commit", "--quiet", "--allow-empty", "-m", subject)
    return git(repo, "rev-parse", "HEAD")


def load_script():
    return find_applied_fixes_recursive


def test_parser_accepts_relationship_labels_errors_and_legacy_lines():
    module = load_script()
    groups = module.parse_fixes(
        io.StringIO(
            "Original change\n"
            "  Fixed-by: aaaaaaaaaaaa First fix\n"
            "    Mentioned-by: bbbbbbbbbbbb Follow-up mention (as title)\n"
            "      cccccccccccc Legacy fix\n"
            "Another change\n"
            "  Error: no matching Fixes: tag or commit-message mention found\n"
        )
    )

    assert groups == [
        (
            "Original change",
            [
                (1, "Fixed-by", "aaaaaaaaaaaa", "First fix", None),
                (2, "Mentioned-by", "bbbbbbbbbbbb", "Follow-up mention", "title"),
                (3, "Fixed-by", "cccccccccccc", "Legacy fix", None),
            ],
        ),
        ("Another change", []),
    ]


def test_present_and_missing_output_preserves_relationships_and_depth():
    with tempfile.TemporaryDirectory(prefix="find-applied-fixes-test-") as directory:
        repo = Path(directory) / "repo"
        repo.mkdir()
        git(repo, "init", "--quiet")
        git(repo, "config", "user.name", "Test User")
        git(repo, "config", "user.email", "test@example.com")
        commit(repo, "Range base")
        git(repo, "tag", "v4.19.19")
        local_fix = commit(repo, "Present fix")
        local_mention = commit(repo, "Present mention")
        input_text = (
            "Original change\n"
            "  Fixed-by: aaaaaaaaaaaa Present fix\n"
            "    Mentioned-by: bbbbbbbbbbbb Missing mention (as abcdef012345)\n"
            "  Mentioned-by: cccccccccccc Present mention (as title)\n"
            "  Error: ignored status\n"
        )

        present = run(
            [sys.executable, "-m", MODULE, "-C", repo, "--show-local-hash"],
            input_text=input_text,
            check=False,
        )
        missing = run(
            [sys.executable, "-m", MODULE, "--repo", repo, "--missing"],
            input_text=input_text,
            check=False,
        )

        assert present.returncode == 0
        assert present.stdout.splitlines() == [
            "Original change",
            f"  Fixed-by: aaaaaaaaaaaa Present fix    [local: {local_fix[:12]}]",
            "  Mentioned-by: cccccccccccc Present mention (as title)    "
            f"[local: {local_mention[:12]}]",
        ]
        assert present.stderr.strip() == (
            "2/3 related commits are already present in v4.19.19..HEAD"
        )

        assert missing.returncode == 0
        assert missing.stdout.splitlines() == [
            "Original change",
            "    Mentioned-by: bbbbbbbbbbbb Missing mention (as abcdef012345)",
        ]
        assert missing.stderr.strip() == ("1/3 related commits are not present in v4.19.19..HEAD")


def test_invalid_repo_has_a_clear_error():
    with tempfile.TemporaryDirectory(prefix="find-applied-fixes-caller-") as directory:
        missing = Path(directory) / "missing"
        result = run(
            [sys.executable, "-m", MODULE, "-C", missing],
            input_text="",
            check=False,
        )

        assert result.returncode == 2
        assert f"cannot access Git repository: {missing}" in result.stderr
