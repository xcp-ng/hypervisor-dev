"""Cherry-pick selection screen for choosing a left commit in the side-by-side diff."""

import subprocess

import pygit2
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label

from ..constants import SolarizedColors
from ..git_utils import abbrev, commit_title
from .utils import cell, cell_from_commit


def _name_rev(repo: pygit2.Repository, commit: pygit2.Commit) -> str:
    result = subprocess.run(
        ["git", "-C", repo.workdir, "name-rev", "--name-only", str(commit.id)],
        capture_output=True,
        text=True,
    )
    name = result.stdout.strip()
    return "" if name == "undefined" else name


def _commit_cell(repo: pygit2.Repository, commit: pygit2.Commit) -> Text:
    c = Text("")
    c.append(abbrev(commit.id), SolarizedColors.Yellow)
    name = _name_rev(repo, commit)
    if name:
        c.append(f" ({name})", SolarizedColors.Red)
    c.append(f" {commit_title(commit)}")
    return cell(c)


class CherryPickScreen(ModalScreen):
    CSS = """
    CherryPickScreen {
        align: center middle;
    }

    #cherry_pick_dialog {
        background: $panel;
        border: thick $primary;
        width: 90;
        height: auto;
        max-height: 30;
        padding: 1 2;
    }

    #cherry_pick_table {
        height: auto;
        max-height: 20;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        right_commit: pygit2.Commit,
        cherry_pick_commits: list[pygit2.Commit],
        repo: pygit2.Repository,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.right_commit = right_commit
        self.cherry_pick_commits = cherry_pick_commits
        self.repo = repo

    def compose(self) -> ComposeResult:
        with Vertical(id="cherry_pick_dialog"):
            yield Label(Text("Select left commit for: ") + cell_from_commit(self.right_commit))
            yield Label("")
            yield DataTable(id="cherry_pick_table")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.show_header = False
        table.add_column("commit")

        none_text = Text("none", SolarizedColors.Base01)
        table.add_row(none_text, key="none")

        for commit in self.cherry_pick_commits:
            table.add_row(_commit_cell(self.repo, commit), key=str(commit.id))

        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value == "none":
            self.dismiss(None)
        else:
            for commit in self.cherry_pick_commits:
                if str(commit.id) == event.row_key.value:
                    self.dismiss(commit)
                    return
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(False)
