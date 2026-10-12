"""Rebase table widget for viewing commit matches."""

import argparse
import subprocess

import pygit2
from rich.style import Style
from rich.text import Text
from textual.message import Message
from textual.widgets import DataTable
from textual.widgets.data_table import CellDoesNotExist, RowKey

from ..backport_matching import BackportMatches
from ..commit_matching import RebasedCommitsMatches
from ..constants import CommitMatchInfoFlag, FilterType, SolarizedColors, commit_match_info_repr
from ..git_utils import cherry_pick_parents
from .cherry_pick_screen import CherryPickScreen
from .search_bar import SearchBar
from .utils import cell_from_commit

# Rows related to the highlighted one, e.g. backports applied out of order with it.
RELATED_ROW_STYLE = Style(bgcolor=SolarizedColors.Violet)


class ShowDiff(Message):
    def __init__(
        self,
        left_commit: pygit2.Commit | None,
        right_commit: pygit2.Commit | None,
    ):
        super().__init__()
        self.left_commit = left_commit
        self.right_commit = right_commit


class RebaseTable(DataTable):

    BINDINGS = [
        ("enter", "show_diff", "Show side-by-side diff"),
        ("c", "comment", "Comment commit"),
        ("p", "pick_cherry_pick_source", "Pick cherry-picked commit"),
    ]

    def __init__(
        self,
        args: argparse.Namespace,
        repo: pygit2.Repository,
        filters: dict[CommitMatchInfoFlag, FilterType],
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.args = args
        self.repo = repo
        self.rebased_commit_matches: None | RebasedCommitsMatches | BackportMatches = None
        self.filters = filters
        self.fuzzy_terms: None | list[str] = None
        self.related_rows: set[pygit2.Oid] = set()
        self.search_bar = SearchBar(fuzzy=True)
        self.column_keys = [
            self.add_column(self.args.left_title, width=80),
            self.add_column(Text("Match type")),
            self.add_column(self.args.right_title, width=80),
        ]

    def action_comment(self) -> None:
        with self.app.suspend():
            subprocess.run(
                ["git", "-C", self.repo.workdir, "notes", "add", str(self.row_key.value)]
            )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        self.row_key = event.row_key
        related: set[pygit2.Oid] = set()
        if isinstance(self.rebased_commit_matches, BackportMatches):
            assert isinstance(event.row_key.value, pygit2.Oid)
            related = self.rebased_commit_matches.out_of_order.get(event.row_key.value, set())
        self.set_related_rows(related)

    def set_related_rows(self, related_rows: set[pygit2.Oid]) -> None:
        changed = self.related_rows ^ related_rows
        self.related_rows = set(related_rows)
        assert self.rebased_commit_matches is not None
        for commit_oid in changed:
            match = self.rebased_commit_matches.commit_matches[commit_oid]
            left_cell, right_cell, _ = self.row_cells(commit_oid, match)
            row_key = RowKey(commit_oid)  # type: ignore
            try:
                self.update_cell(row_key, self.column_keys[0], left_cell)
                self.update_cell(row_key, self.column_keys[2], right_cell)
            except CellDoesNotExist:
                # Filtered out.
                pass

    def row_cells(self, commit_oid: pygit2.Oid, match) -> tuple[Text, Text, bool]:
        """Return the left and right cells, and whether they match the fuzzy search."""
        left_cell = cell_from_commit(match.left_commit)
        right_cell = cell_from_commit(match.right_commit)
        fuzzy_matched = True
        for term in self.fuzzy_terms or []:
            if term not in left_cell and term not in right_cell:
                fuzzy_matched = False
                break
            left_cell.highlight_words([term], style="reverse")
            right_cell.highlight_words([term], style="reverse")
        if commit_oid in self.related_rows:
            left_cell.stylize(RELATED_ROW_STYLE)
            right_cell.stylize(RELATED_ROW_STYLE)
        return left_cell, right_cell, fuzzy_matched

    def _push_cherry_pick_screen(self, right_commit: pygit2.Commit) -> bool:
        """Let the user pick the left commit among the cherry-picked ones, if any."""
        cherry_commits: list[pygit2.Commit] = []
        for sha1 in cherry_pick_parents(right_commit):
            try:
                commit = self.repo.get(pygit2.Oid(hex=sha1))
                if isinstance(commit, pygit2.Commit):
                    cherry_commits.append(commit)
            except Exception:
                pass
        if not cherry_commits:
            return False

        def handle_selection(result, right: pygit2.Commit = right_commit) -> None:
            if result is not False:
                self.post_message(ShowDiff(result, right))

        self.app.push_screen(
            CherryPickScreen(right_commit, cherry_commits, self.repo, self.args.name_rev),
            handle_selection,
        )
        return True

    def action_show_diff(self) -> None:
        assert self.rebased_commit_matches is not None
        assert isinstance(self.row_key.value, pygit2.Oid)
        match = self.rebased_commit_matches.commit_matches[self.row_key.value]

        if CommitMatchInfoFlag.Added in match.match_info:
            assert match.right_commit is not None
            if self._push_cherry_pick_screen(match.right_commit):
                return

        self.action_select_cursor()

    def action_pick_cherry_pick_source(self) -> None:
        assert self.rebased_commit_matches is not None
        assert isinstance(self.row_key.value, pygit2.Oid)
        match = self.rebased_commit_matches.commit_matches[self.row_key.value]

        if match.right_commit is None or not self._push_cherry_pick_screen(match.right_commit):
            self.notify("No cherry-picked commit found in this commit message")

    def on_mount(self) -> None:
        self.loading = True
        self.cursor_type = "row"
        self.wrap = False
        self.zebra_stripes = True
        self.styles.height = "100%"

    def on_resize(self) -> None:
        self.update_column_widths()

    def update_column_widths(self) -> None:
        total_width = self.scrollable_content_region.width - 4
        middle_width = 16
        side_width = (total_width - middle_width) // 2
        self.columns[self.column_keys[0]].width = side_width
        self.columns[self.column_keys[1]].width = middle_width
        self.columns[self.column_keys[2]].width = side_width
        self.refresh()

    def set_filters(self, filters: dict[CommitMatchInfoFlag, FilterType]):
        if filters == self.filters:
            return
        self.filters = filters
        self.reload_table()

    async def set_fuzzy_search(self, fuzzy_search: str) -> None:
        def split_terms():
            return [t for t in fuzzy_search.split(" ") if t]

        fuzzy_terms = split_terms()
        if self.fuzzy_terms == fuzzy_terms:
            return
        self.fuzzy_terms = fuzzy_terms
        self.reload_table()

    def load_ranges(self, rebased_commit_matches: RebasedCommitsMatches | BackportMatches) -> None:
        self.rebased_commit_matches = rebased_commit_matches
        self.reload_table()
        self.update_column_widths()
        self.loading = False

    def reload_table(self):
        def markers_from_match_type(match_type):
            match_markers = Text("")
            for match_info in CommitMatchInfoFlag:
                if match_info in match_type:
                    match_markers += commit_match_info_repr[match_info].character
            match_markers.align("center", width=self.columns[self.column_keys[1]].width)
            return match_markers

        def commit_filtered_out():
            for match_type, filter_type in self.filters.items():
                match filter_type:
                    case FilterType.NoFilter:
                        continue
                    case FilterType.With:
                        if match_type not in rebased_commit_match.match_info:
                            return True
                    case FilterType.Without:
                        if match_type in rebased_commit_match.match_info:
                            return True
            return not fuzzy_matched

        self.clear(columns=False)

        assert self.rebased_commit_matches is not None
        for commit_oid, rebased_commit_match in self.rebased_commit_matches.commit_matches.items():
            left_cell, right_cell, fuzzy_matched = self.row_cells(commit_oid, rebased_commit_match)

            if commit_filtered_out():
                continue

            # assert isinstance(commit_oid, str), f"{commit_oid} type ({type(commit_oid)}) != str"
            self.add_row(
                left_cell,
                markers_from_match_type(rebased_commit_match.match_info),
                right_cell,
                key=commit_oid,  # type: ignore
            )
