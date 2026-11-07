"""Screen listing the upstream fixes of a commit which were not backported."""

from datetime import datetime

import pygit2
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label

from ..constants import SolarizedColors
from .utils import cell, cell_from_commit


def _fix_cell(fix: pygit2.Commit) -> Text:
    # No name-rev here, as it takes seconds per commit on large repositories.
    date = datetime.fromtimestamp(fix.commit_time).strftime("%Y-%m-%d")
    return cell(Text(date + " ", SolarizedColors.Base01) + cell_from_commit(fix))


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
        missing_fixes: list[pygit2.Commit],
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
        table.show_header = False
        table.add_column("fix")
        for fix in self.missing_fixes:
            table.add_row(_fix_cell(fix), key=str(fix.id))
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        for fix in self.missing_fixes:
            if str(fix.id) == event.row_key.value:
                self.dismiss(fix)
                return
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
