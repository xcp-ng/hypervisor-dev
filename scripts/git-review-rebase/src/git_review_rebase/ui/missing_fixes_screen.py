"""Screen listing the upstream fixes of a commit, and their own fixes, which were not backported."""

from datetime import datetime

import pygit2
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label

from ..constants import SolarizedColors
from ..git_utils import abbrev
from ..upstream_fixes import MissingFix
from .utils import cell, cell_from_commit


def _date_cell(fix: MissingFix) -> Text:
    return Text(
        datetime.fromtimestamp(fix.commit.commit_time).strftime("%Y-%m-%d"), SolarizedColors.Base01
    )


def _fixed_commit_cell(fix: MissingFix) -> Text:
    # Shown even for nested fixes, as the fixed commit is not listed when it was backported.
    return Text(abbrev(fix.fixed_commit.id), SolarizedColors.Yellow)


def _fix_cell(fix: MissingFix) -> Text:
    # No name-rev here, as it takes seconds per commit on large repositories.
    indent = Text("  " * (fix.depth - 1) + "↳ ", SolarizedColors.Base01) if fix.depth else Text("")
    return cell(indent + cell_from_commit(fix.commit))


class MissingFixesScreen(ModalScreen):
    CSS = """
    MissingFixesScreen {
        align: center middle;
    }

    #missing_fixes_dialog {
        background: $panel;
        border: thick $primary;
        width: 100;
        height: auto;
        max-height: 30;
        padding: 1 2;
    }

    #missing_fixes_table {
        height: auto;
        max-height: 20;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        upstream_commit: pygit2.Commit,
        missing_fixes: list[MissingFix],
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.upstream_commit = upstream_commit
        self.missing_fixes = missing_fixes

    def compose(self) -> ComposeResult:
        with Vertical(id="missing_fixes_dialog"):
            yield Label(
                Text("Missing upstream fixes of: ") + cell_from_commit(self.upstream_commit)
            )
            yield Label("")
            yield DataTable(id="missing_fixes_table")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_column("Date")
        table.add_column("Fixes")
        table.add_column("Missing fix")
        for fix in self.missing_fixes:
            table.add_row(
                _date_cell(fix), _fixed_commit_cell(fix), _fix_cell(fix), key=str(fix.commit.id)
            )
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        for fix in self.missing_fixes:
            if str(fix.commit.id) == event.row_key.value:
                self.dismiss(fix.commit)
                return
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
