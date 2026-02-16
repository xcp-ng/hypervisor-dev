import argparse
import asyncio

import pygit2

from pygments.formatters import Terminal256Formatter

from rich.syntax import Syntax
from rich.text import Text

from textual import work, log
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.reactive import var
from textual.widgets import DataTable, Footer, Header, LoadingIndicator, Static

from ..symtypes import SymTypes


class SymbolTable(DataTable):
    DEFAULT_CSS = """
    SymbolTable {
        width: 20%
    }
    """

    def on_mount(self):
        self.cursor_type = "row"
        self.add_column("Changed symbols")

    def add_row(self, cell, *args, **kwargs):
        super().add_row(
            Syntax(
                cell,
                lexer="c",
                theme="solarized-dark",
                background_color="#073642",
            )
        )


class TitledHeader(Header):
    def __init__(self, title, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = title

    def format_title(self) -> Content:
        return Text(self.title)

class KabiTuiApp(App):
    loaded: var[bool] = var(False)

    def __init__(self, args: argparse.Namespace):
        super().__init__()
        self.args = args
        self.repo = pygit2.Repository(args.repository)

    def start(self) -> None:
        print("App started")
        print(self.args)

    def compose(self) -> ComposeResult:
        self.startup_loading_indicator = LoadingIndicator()
        self.symbols = SymbolTable()
        self.symbol_diff = Vertical(
            TitledHeader(title="Symbol diff"),
            Static()
        )
        self.struct_holes = Vertical(
            TitledHeader(title="Holes"),
            Static()
        )
        self.impacted_modules = Vertical(
            TitledHeader(title="Modules impacted",),
            DataTable()
        )
        self.guilty_commits = Vertical(
            TitledHeader(title="Infringuing commits"),
            DataTable()
        )
        self.body = Horizontal(
            self.symbols,
            Vertical(
                Horizontal(
                    Vertical(
                        self.symbol_diff,
                        self.impacted_modules
                    ),
                    self.struct_holes,
                ),
                self.guilty_commits
            ),
        )

        yield Header(show_clock=True)
        yield self.startup_loading_indicator
        yield self.body
        yield Footer()

    def on_mount(self) -> None:
        self.theme = "solarized-dark"
        self.body.display = False
        self.startup_loading_indicator.display = True
        self.load_data()

    def watch_loaded(self, loaded: bool) -> None:
        if loaded:
            self.startup_loading_indicator.display = False
            self.body.display = True

    def symbol_key(self, key):
        symbol = key[0]
        if len(symbol) > 2 and symbol[1] == "#":
            return "." + symbol
        return symbol

    @work
    async def load_data(self) -> None:
        self.old_symtypes = SymTypes.from_file(self.args.symtypes_lhs)
        self.new_symtypes = SymTypes.from_file(self.args.symtypes_rhs)
        self.common_symbols = self.old_symtypes.exports.keys() & self.new_symtypes.exports.keys()

        differing_types: set[tuple[str, str, str]] = set()

        for symbol in self.common_symbols:
            await asyncio.sleep(0)
            if self.old_symtypes.crc(symbol) == self.new_symtypes.crc(symbol):
                continue
            differing_types |= SymTypes.identify_kabi_difference(self.old_symtypes, self.new_symtypes, symbol)

        for symbol, _, _ in sorted(differing_types, key=self.symbol_key):
            self.symbols.add_row(self.old_symtypes.name(symbol))
        self.loaded = True
