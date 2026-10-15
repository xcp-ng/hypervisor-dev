import contextlib
import importlib
import io
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from commit_graph_tools import find_fixers_recursive

MODULE = "commit_graph_tools.find_fixers_recursive"


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


def commit(repo, subject, body=None):
    args = ["commit", "--quiet", "--allow-empty", "-m", subject]

    if body is not None:
        args.extend(["-m", body])

    git(repo, *args)
    return git(repo, "rev-parse", "HEAD")


@contextlib.contextmanager
def repository():
    with tempfile.TemporaryDirectory(prefix="find-fixers-test-") as directory:
        repo = Path(directory) / "repo"
        repo.mkdir()
        git(repo, "init", "--quiet")
        git(repo, "config", "user.name", "Test User")
        git(repo, "config", "user.email", "test@example.com")
        yield repo


def run_script(repo, input_text, source_ranges, fix_range, *, quiet=True):
    command = [sys.executable, "-m", MODULE, "--repo", repo]

    if quiet:
        command.append("--quiet")

    for source_range in source_ranges:
        command.extend(["--source-range", source_range])

    command.extend(["--fix-range", fix_range])

    # Deliberately run outside repo to verify that --repo controls every Git
    # command without requiring the caller to change directories.
    return run(command, cwd=Path(__file__).parent, input_text=input_text, check=False)


@pytest.mark.parametrize("input_mode", ["stdin", "explicit-stdin", "file", "target-range"])
def test_input_modes_select_the_same_commits_in_order(input_mode):
    with repository() as repo:
        base = commit(repo, "Excluded base")
        first = commit(repo, "First original")
        second = commit(repo, "Second original")
        git(repo, "branch", "inputs")
        first_fix = commit(repo, "First correction", f"Fixes: {first[:12]}")
        second_fix = commit(repo, "Second correction", f"Fixes: {second[:12]}")
        commit(repo, "Excluded base correction", f"Fixes: {base[:12]}")
        head = git(repo, "rev-parse", "HEAD")
        input_text = f"{first[:7]} First original\n{second[:7]} Second original\n"
        command = [
            sys.executable,
            "-m",
            MODULE,
            "--repo",
            repo,
            "--quiet",
            "--source-range",
            f"{base}..HEAD",
            "--fix-range",
            f"{base}..HEAD",
        ]

        if input_mode == "target-range":
            command.extend(["--target-range", f"{base}..inputs"])
            # Range mode must ignore stdin, even when it contains valid input.
            input_text = f"{base} Excluded base\n"
        elif input_mode == "file":
            input_file = repo / "commits.txt"
            input_file.write_text(input_text, encoding="utf-8")
            command.append(str(input_file))
            input_text = f"{base} Excluded base\n"
        elif input_mode == "explicit-stdin":
            command.append("-")

        result = run(command, cwd=Path(__file__).parent, input_text=input_text, check=False)

        assert result.returncode == 0
        assert result.stderr == ""
        assert result.stdout.splitlines() == [
            f"{first[:12]} First original",
            f"  Fixed-by: {first_fix[:12]} First correction",
            f"{second[:12]} Second original",
            f"  Fixed-by: {second_fix[:12]} Second correction",
        ]
        assert git(repo, "rev-parse", "HEAD") == head


@pytest.mark.parametrize("input_file", ["commits.txt", "-"])
def test_target_range_cannot_be_combined_with_file_input(input_file):
    result = run(
        [sys.executable, "-m", MODULE, "--target-range", "base..HEAD", input_file],
        input_text="",
        check=False,
    )

    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("input_range", ["does-not-exist..HEAD", "--all", ""])
def test_invalid_target_range_has_a_clear_error(input_range):
    with repository() as repo:
        commit(repo, "Base")
        result = run(
            [
                sys.executable,
                "-m",
                MODULE,
                "--repo",
                repo,
                "--quiet",
                f"--target-range={input_range}",
            ],
            input_text="",
            check=False,
        )

        assert result.returncode == 2
        assert f"cannot read input revision range: {input_range}" in result.stderr
        assert "Traceback" not in result.stderr
        assert result.stdout == ""


def test_empty_target_range_does_not_fall_back_to_stdin():
    with repository() as repo:
        base = commit(repo, "Base")
        original = commit(repo, "Original change")
        commit(repo, "Correction", f"Fixes: {original[:12]}")
        result = run(
            [
                sys.executable,
                "-m",
                MODULE,
                "--repo",
                repo,
                "--quiet",
                "--target-range",
                "HEAD..HEAD",
                "--source-range",
                f"{base}..HEAD",
                "--fix-range",
                f"{base}..HEAD",
            ],
            input_text=f"{original} Original change\n",
            check=False,
        )

        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""


def test_fixes_and_mentions_are_both_recursive():
    with repository() as repo:
        base = commit(repo, "Base")
        git(repo, "branch", "upstream", base)
        git(repo, "switch", "--quiet", "upstream")
        upstream = commit(repo, "Original change with spacing")

        git(repo, "switch", "--quiet", "--create", "stable", base)
        commit(repo, "Stable preparation")
        local = commit(repo, "Original change with spacing")

        direct_fix = commit(
            repo,
            "Direct correction",
            f'Fixes: {upstream[:12]} ("Original change with spacing")',
        )
        direct_mention = commit(
            repo,
            "Discussion of original",
            "The change named:\n\n    Original\tchange\n        with   spacing\nis relevant here.",
        )
        fix_of_fix = commit(
            repo,
            "Correction follow-up",
            f'Fixes: {direct_fix[:12]} ("Direct correction")',
        )
        mention_of_fix = commit(
            repo,
            "Discussion of correction",
            "This expands on Direct\n    correction.",
        )
        fix_of_mention = commit(
            repo,
            "Discussion correction",
            f'Fixes: {direct_mention[:12]} ("Discussion of original")',
        )
        mention_of_mention = commit(
            repo,
            "Further discussion",
            "This follows Discussion of\n    original.",
        )

        result = run_script(
            repo,
            f"{local} Original change with spacing\n",
            [f"{base}..upstream", f"{base}..stable"],
            f"{base}..stable",
        )

        assert result.returncode == 0
        assert result.stderr == ""
        assert result.stdout.splitlines() == [
            f"{local[:12]} Original change with spacing",
            f"  Fixed-by: {direct_fix[:12]} Direct correction",
            f"    Fixed-by: {fix_of_fix[:12]} Correction follow-up",
            f"    Mentioned-by: {mention_of_fix[:12]} Discussion of correction (as title)",
            f"  Mentioned-by: {direct_mention[:12]} Discussion of original (as title)",
            f"    Fixed-by: {fix_of_mention[:12]} Discussion correction",
            f"    Mentioned-by: {mention_of_mention[:12]} Further discussion (as title)",
        ]


def test_mentions_match_upstream_and_cherry_picked_hashes():
    with repository() as repo:
        base = commit(repo, "Base")
        git(repo, "branch", "upstream", base)
        git(repo, "switch", "--quiet", "upstream")
        upstream = commit(repo, "Original identity")

        git(repo, "switch", "--quiet", "--create", "stable", base)
        commit(repo, "Stable preparation")
        local = commit(repo, "Original identity")
        upstream_reference = commit(
            repo,
            "Upstream hash reference",
            f"References upstream commit {upstream[:12]}.",
        )
        local_reference = commit(
            repo,
            "Cherry-pick hash reference",
            f"References backport commit {local[:12]}.",
        )

        result = run_script(
            repo,
            f"{local[:12]} Original identity\n",
            [f"{base}..upstream", f"{base}..stable"],
            f"{base}..stable",
        )

        assert result.returncode == 0
        assert result.stderr == ""
        assert result.stdout.splitlines() == [
            f"{local[:12]} Original identity",
            f"  Mentioned-by: {local_reference[:12]} Cherry-pick hash reference (as {local[:12]})",
            f"  Mentioned-by: {upstream_reference[:12]} Upstream hash reference "
            f"(as {upstream[:12]})",
        ]


def test_backport_markers_add_original_hashes_to_mention_search():
    with repository() as repo:
        base = commit(repo, "Base")
        upstream_hash = "123456789abc" + "1" * 28
        cherry_pick_hash = "abcdef012345" + "2" * 28
        backport = commit(
            repo,
            "Backported change",
            f"commit {upstream_hash} upstream.\n\n(cherry picked from commit {cherry_pick_hash})",
        )
        upstream_reference = commit(
            repo,
            "Reference upstream identity",
            f"This refers to {upstream_hash[:12]}.",
        )
        cherry_pick_reference = commit(
            repo,
            "Reference cherry-pick identity",
            f"This refers to {cherry_pick_hash}.",
        )
        commit_range = f"{base}..HEAD"

        result = run_script(
            repo,
            f"{backport} Backported change\n",
            [commit_range],
            commit_range,
        )

        assert result.returncode == 0
        assert result.stderr == ""
        assert result.stdout.splitlines() == [
            f"{backport[:12]} Backported change",
            f"  Mentioned-by: {cherry_pick_reference[:12]} Reference cherry-pick "
            f"identity (as {cherry_pick_hash[:12]})",
            f"  Mentioned-by: {upstream_reference[:12]} Reference upstream "
            f"identity (as {upstream_hash[:12]})",
        ]


def test_hash_message_search_uses_at_most_twelve_characters():
    first = "0123456789ab" + "1" * 28
    second = "0123456789ab" + "2" * 28

    assert find_fixers_recursive.hash_search_key(first) == "0123456789ab"
    assert find_fixers_recursive.hashes_match(first, second)


def test_fixes_tag_can_point_to_a_commit_on_another_branch():
    with repository() as repo:
        base = commit(repo, "Base")
        git(repo, "branch", "upstream", base)
        git(repo, "switch", "--quiet", "upstream")
        upstream = commit(repo, "Upstream-only change")

        git(repo, "switch", "--quiet", "--create", "stable", base)
        fixer = commit(
            repo,
            "Cross-branch fix",
            f'Fixes: {upstream[:12]} ("Upstream-only change")',
        )

        result = run_script(
            repo,
            f"{upstream} Upstream-only change\n",
            [f"{base}..upstream"],
            f"{base}..stable",
        )

        assert result.returncode == 0
        assert result.stderr == ""
        assert result.stdout.splitlines() == [
            f"{upstream[:12]} Upstream-only change",
            f"  Fixed-by: {fixer[:12]} Cross-branch fix",
        ]


def test_hash_mention_can_point_to_a_commit_on_another_branch():
    with repository() as repo:
        base = commit(repo, "Base")
        git(repo, "branch", "upstream", base)
        git(repo, "switch", "--quiet", "upstream")
        upstream = commit(repo, "Upstream-only change")

        git(repo, "switch", "--quiet", "--create", "stable", base)
        mention = commit(
            repo,
            "Cross-branch reference",
            f"This refers to upstream commit {upstream[:7]}.",
        )

        result = run_script(
            repo,
            f"{upstream} Upstream-only change\n",
            [f"{base}..upstream"],
            f"{base}..stable",
        )

        assert result.returncode == 0
        assert result.stderr == ""
        assert result.stdout.splitlines() == [
            f"{upstream[:12]} Upstream-only change",
            f"  Mentioned-by: {mention[:12]} Cross-branch reference (as {upstream[:7]})",
        ]


def test_title_only_match_can_point_to_another_branch():
    with repository() as repo:
        base = commit(repo, "Base")
        git(repo, "branch", "upstream", base)
        git(repo, "switch", "--quiet", "upstream")
        upstream = commit(repo, "Repeated title")

        git(repo, "switch", "--quiet", "--create", "stable", base)
        mention = commit(
            repo,
            "Coincidental discussion",
            "This happens to say Repeated title without identifying a commit.",
        )

        result = run_script(
            repo,
            f"{upstream} Repeated title\n",
            [f"{base}..upstream"],
            f"{base}..stable",
        )

        assert result.returncode == 0
        assert result.stderr == ""
        assert result.stdout.splitlines() == [
            f"{upstream[:12]} Repeated title",
            f"  Mentioned-by: {mention[:12]} Coincidental discussion (as title)",
        ]


def test_fix_range_limits_the_commits_that_are_searched():
    with repository() as repo:
        base = commit(repo, "Base")
        original = commit(repo, "Original change")
        fixer = commit(
            repo,
            "Fix original change",
            f'Fixes: {original[:12]} ("Original change")',
        )
        source_range = f"{base}..HEAD"

        excluded = run_script(
            repo,
            f"{original} Original change\n",
            [source_range],
            f"{base}..{original}",
        )
        included = run_script(
            repo,
            f"{original} Original change\n",
            [source_range],
            f"{base}..HEAD",
        )

        assert excluded.returncode == 0
        assert excluded.stdout == ""
        assert included.returncode == 0
        assert included.stdout.splitlines() == [
            f"{original[:12]} Original change",
            f"  Fixed-by: {fixer[:12]} Fix original change",
        ]


def test_errors_are_reported_without_out_of_range_fixes_spew():
    with repository() as repo:
        old_target = commit(repo, "Old target")
        base = commit(repo, "Range base")
        original = commit(repo, "Unfixed original")
        commit(
            repo,
            "Fix outside range target",
            f'Fixes: {old_target[:12]} ("Old target")',
        )
        commit_range = f"{base}..HEAD"

        result = run_script(
            repo,
            (f"{original} Unfixed original\nffffffffffff Missing original\n"),
            [commit_range],
            commit_range,
        )

        assert result.returncode == 0
        assert result.stderr == ""
        assert result.stdout.splitlines() == [
            "ffffffffffff Missing original",
            f"  Error: original commit not found in {commit_range}",
        ]


def test_merge_only_mention_subtrees_are_pruned():
    with repository() as repo:
        base = commit(repo, "Base")
        original = commit(repo, "Original change")
        commit(
            repo,
            "Merge branch 'topic'",
            "Merge work related to Original change.",
        )
        commit(
            repo,
            "Merge tag 'follow-up'",
            "This follows Merge branch 'topic'.",
        )
        commit_range = f"{base}..HEAD"

        result = run_script(
            repo,
            f"{original} Original change\n",
            [commit_range],
            commit_range,
        )

        assert result.returncode == 0
        assert result.stderr == ""
        assert result.stdout == ""


def test_merge_mention_is_retained_when_it_leads_to_a_real_relationship():
    with repository() as repo:
        base = commit(repo, "Base")
        original = commit(repo, "Original change")
        merge = commit(
            repo,
            "Merge branch 'topic'",
            "Merge work related to Original change.",
        )
        fixer = commit(
            repo,
            "Fix merged work",
            f'Fixes: {merge[:12]} ("Merge branch topic")',
        )
        commit_range = f"{base}..HEAD"

        result = run_script(
            repo,
            f"{original} Original change\n",
            [commit_range],
            commit_range,
        )

        assert result.returncode == 0
        assert result.stderr == ""
        assert result.stdout.splitlines() == [
            f"{original[:12]} Original change",
            f"  Mentioned-by: {merge[:12]} Merge branch 'topic' (as title)",
            f"    Fixed-by: {fixer[:12]} Fix merged work",
        ]


def test_recursive_alias_mentions_report_the_matching_hash():
    with repository() as repo:
        base = commit(repo, "Base")
        original = commit(repo, "Original change")
        alias_subject = "A change related to the original"
        first_copy = commit(repo, alias_subject, "This includes Original change.")
        other_copy = commit(repo, alias_subject, "Another copy of the change.")
        unrelated = commit(
            repo,
            "Unrelated change",
            f"A build happened to use kernel g{other_copy[:12]}.",
        )
        commit_range = f"{base}..HEAD"

        result = run_script(
            repo,
            f"{original} Original change\n",
            [commit_range],
            commit_range,
        )

        assert result.returncode == 0
        assert result.stderr == ""
        assert result.stdout.splitlines() == [
            f"{original[:12]} Original change",
            f"  Mentioned-by: {first_copy[:12]} {alias_subject} (as title)",
            f"    Mentioned-by: {unrelated[:12]} Unrelated change (as {other_copy[:12]})",
        ]


@pytest.mark.parametrize(
    "merge_subject",
    [
        "Merge branch 'topic'",
        "Merge branches 'first' and 'second'",
        "Merge tag 'fixes' of git://example.com/subsystem",
        "Merge git://git.kernel.org/pub/scm/linux/kernel/git/davem/net",
    ],
)
@pytest.mark.parametrize("preloaded_sources", [False, True])
def test_merge_titles_do_not_create_equivalent_identities(merge_subject, preloaded_sources):
    with repository() as repo:
        base = commit(repo, "Base")
        original = commit(repo, "Original change")
        first_merge = commit(repo, merge_subject, "Pull fixes including Original change.")
        other_merge = commit(repo, merge_subject, "A later, unrelated pull.")
        commit(repo, "Unrelated fix", f"Fixes: {other_merge[:12]}")
        commit(repo, "Unrelated mention", f"References {other_merge[:12]}.")
        direct_fix = commit(repo, "Fix the first merge", f"Fixes: {first_merge[:12]}")
        direct_mention = commit(repo, "Discuss the first merge", f"References {first_merge[:12]}.")
        commit_range = f"{base}..HEAD"
        source_range = commit_range if preloaded_sources else f"{base}..{direct_mention}"

        result = run_script(
            repo,
            f"{original} Original change\n{first_merge} {merge_subject}\n",
            [source_range],
            commit_range,
        )

        assert result.returncode == 0
        assert result.stderr == ""
        assert result.stdout.splitlines() == [
            f"{original[:12]} Original change",
            f"  Mentioned-by: {first_merge[:12]} {merge_subject} (as title)",
            f"    Fixed-by: {direct_fix[:12]} Fix the first merge",
            f"    Mentioned-by: {direct_mention[:12]} Discuss the first merge "
            f"(as {first_merge[:12]})",
            f"{first_merge[:12]} {merge_subject}",
            f"  Fixed-by: {direct_fix[:12]} Fix the first merge",
            f"  Mentioned-by: {direct_mention[:12]} Discuss the first merge "
            f"(as {first_merge[:12]})",
        ]


def test_invalid_repo_has_a_clear_error():
    with tempfile.TemporaryDirectory(prefix="find-fixers-caller-") as directory:
        missing = Path(directory) / "missing"
        result = run(
            [sys.executable, "-m", MODULE, "--repo", missing],
            input_text="",
            check=False,
        )

        assert result.returncode == 2
        assert f"cannot access Git repository: {missing}" in result.stderr


def test_progress_is_reported_on_stderr():
    with repository() as repo:
        base = commit(repo, "Base")
        original = commit(repo, "Original change")
        commit_range = f"{base}..HEAD"

        result = run_script(
            repo,
            f"{original} Original change\n",
            [commit_range],
            commit_range,
            quiet=False,
        )

        assert result.returncode == 0
        assert result.stdout == ""
        assert "[1/6] Read input commits" in result.stderr
        assert "[5/6] Build fixes and mention indexes" in result.stderr
        assert "[6/6] Find recursive relationships" in result.stderr
        assert "1/1  Original change" in result.stderr
        assert "Done  1 commit, 0 relationships in" in result.stderr


def test_unresolved_and_ambiguous_fixes_targets_are_handled_differently():
    module = importlib.reload(find_fixers_recursive)
    fixer = {
        "hash": "f" * 40,
        "subject": "Fixer",
    }

    missing_stderr = io.StringIO()

    with contextlib.redirect_stderr(missing_stderr):
        missing = module.resolve_fixes_target(
            "deadbee",
            None,
            fixer,
            [],
            {},
        )

    ambiguous_stderr = io.StringIO()

    with contextlib.redirect_stderr(ambiguous_stderr):
        ambiguous = module.resolve_fixes_target(
            "abcdef0",
            None,
            fixer,
            ["abcdef0" + "1" * 33, "abcdef0" + "2" * 33],
            {},
        )

    assert missing is None
    assert missing_stderr.getvalue() == ""
    assert ambiguous is None
    assert "warning: ambiguous Fixes target abcdef0" in ambiguous_stderr.getvalue()


def test_input_hash_resolution_uses_one_batch_process():
    module = importlib.reload(find_fixers_recursive)
    calls = []
    first = "a" * 12
    second = "b" * 12

    def fake_git(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=f"{'a' * 40} commit\n{second}^{{commit}} missing\n",
            stderr="",
        )

    module.git = fake_git  # type: ignore
    resolved = module.resolve_input_hashes([first, second, first, "invalid"])

    assert resolved == {first: "a" * 40}
    assert len(calls) == 1
    assert calls[0][0] == (
        "cat-file",
        "--batch-check=%(objectname) %(objecttype)",
    )
    assert calls[0][1]["input_text"].splitlines() == [
        f"{first}^{{commit}}",
        f"{second}^{{commit}}",
    ]
