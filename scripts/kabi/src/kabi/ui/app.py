import argparse
import asyncio

import pygit2

import re

from enum import StrEnum

from rich.syntax import Syntax
from rich.text import Text, Span
from rich.style import Style

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.events import DescendantBlur, DescendantFocus
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, LoadingIndicator, Static
from ..symtypes import SymTypes


class SolarizedColors(StrEnum):
    # Darker to Lighter
    Base03 = "#002b36"
    Base02 = "#073642"
    Base01 = "#586e75"
    Base00 = "#657b83"
    Base0 = "#839496"
    Base1 = "#93a1a1"
    Base2 = "#eee8d5"
    Base3 = "#fdf6e3"
    Yellow = "#b58900"
    Orange = "#cb4b16"
    Red = "#dc322f"
    Magenta = "#d33682"
    Violet = "#6c71c4"
    Blue = "#268bd2"
    Cyan = "#2aa198"
    Green = "#859900"


def clear_background(t: Text) -> Text:
    spans = []
    t.style = None
    for span in t.spans:
        if not isinstance(span.style, Style):
            continue
        style = span.style
        spans.append(
            Span(
                style=style.color.name,
                start=span.start,
                end=span.end
            )
        )
    t.spans = spans
    return t


class HighlightedLog(VerticalScroll):
    def __init__(self, lexer: None | str = "c", theme: None | str = "solarized-dark", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.syntax = Syntax(
            "",
            lexer=lexer,
            theme=theme,
            background_color="default",
        )
        self.content = Text("")

    def compose(self) -> ComposeResult:
        yield Static()

    def clear(self) -> None:
        self.content = Text("")

    def write_line(self, line: str, *args, **kwargs):
        line = clear_background(self.syntax.highlight(line))
        self.content.append_text(
            line
        )
        self.query_one(Static).content = self.content


class TitledVertical(Vertical):
    def __init__(self, *args, **kwargs):
        self.title = kwargs.pop("title") if "title" in kwargs else "unknowntitle"
        super().__init__(*args, **kwargs)

    def compose(self) -> ComposeResult:
        yield TitledHeader(title=self.title)
        yield from super().compose()

    def on_descendant_focus(self, event: DescendantFocus) -> None:
        self.query_one(TitledHeader).toggle_class("-focused")

    def on_descendant_blur(self, event: DescendantBlur) -> None:
        self.query_one(TitledHeader).toggle_class("-focused")


class HighlightedTable(DataTable):
    def __init__(self, lexer: None | str = "c", theme: None | str = "solarized-dark", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.syntax = Syntax(
            "",
            lexer=lexer,
            theme=theme,
            background_color="default",
        )

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.add_column("Changed symboles")

    def add_row(self, line, *args, **kwargs):
        line = self.syntax.highlight(line)
        super().add_row(clear_background(line), *args, **kwargs)


class TitledHeader(Header):

    DEFAULT_CSS = """
    TitledHeader.-focused {
        background: $footer-background
    }
"""

    def __init__(self, title: str | Text, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = title

    def set_title(self, title: str | Text) -> None:
        self.title = title
        self.query_one("HeaderTitle").update(
            self.format_title()
        )

    def format_title(self) -> Content:
        if isinstance(self.title, Text):
            return self.title
        return Text(self.title)


class KabiTuiApp(App):

    DEFAULT_CSS = """
    CSymbolTable > {
        height: 100%
    }
    #main {
        width: 1fr
    }
    #main-horizontal {
        height: 5fr
    }
    #guilty-commits  {
        height: 1fr
    }
    #impacted-modules {
        height: 1fr
    }
    #symbol-diff {
        height: 4fr
    }
    """

    BINDINGS = [
        ("n", "toggle_old_new", "Toggle between old/new structs.")
    ]

    loaded: reactive[bool] = reactive(False)

    def __init__(self, args: argparse.Namespace):
        super().__init__()
        self.args = args
        self.repo = pygit2.Repository(args.repository)
        self.struct_version = "old"

    async def action_toggle_old_new(self) -> None:
        self.struct_version = "old" if self.struct_version == "new" else "new"
        await self.refresh_all()

    def start(self) -> None:
        print("App started")
        print(self.args)

    def compose(self) -> ComposeResult:
        self.startup_loading_indicator = LoadingIndicator()
        self.symbols = HighlightedTable()
        self.symbol_diff = Vertical(
            TitledHeader(title="Symbol diff"),
            DataTable(),
            id="symbol-diff"
        )
        self.struct_holes = TitledVertical(
            HighlightedLog(),
            title="Holes",
        )
        self.impacted_modules = Vertical(
            TitledHeader(title="Modules impacted",),
            DataTable(),
            id="impacted-modules"
        )
        self.guilty_commits = Vertical(
            TitledHeader(title="Infringuing commits"),
            DataTable(),
            id="guilty-commits"
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
                    id="main-horizontal"
                ),
                self.guilty_commits,
                id="main"
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
        self.symbols.styles.width = "20%"

        self.old_symtypes = SymTypes.from_file(self.args.symtypes_lhs)
        self.new_symtypes = SymTypes.from_file(self.args.symtypes_rhs)
        self.common_symbols = self.old_symtypes.exports.keys() & self.new_symtypes.exports.keys()

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
        differing_types: set[tuple[str, str, str]] = set()

        for symbol in self.common_symbols:
            await asyncio.sleep(0)
            if self.old_symtypes.crc(symbol) == self.new_symtypes.crc(symbol):
                continue
            differing_types |= SymTypes.identify_kabi_difference(self.old_symtypes, self.new_symtypes, symbol)

        for symbol, _, _ in sorted(differing_types, key=self.symbol_key):
            self.symbols.add_row(self.old_symtypes.name(symbol), key=symbol)
        self.loaded = True

    async def on_data_table_row_selected(self, event: DataTable.RowSelected):
        if event.data_table == self.symbols:
            self.symbol = event.row_key.value
            await self.refresh_all()

    async def refresh_all(self) -> None:
        await self.refresh_holes(self.symbol)
        await self.refresh_diff(self.symbol)

    async def refresh_diff(self, symbole: str) -> None:
        pass

    # /* <3d8c> ./include/linux/mutex.h:53 */
    include_header_re = re.compile(r"/[*] <(?P<symver>[a-f0-9]+)> ([.]/)?(?P<header>[^:]+):(?P<line_number>[0-9]+) [*]/")

    def get_header_title(self, symbol: str, line: str) -> Text:
        symbol = self.old_symtypes.name(symbol)
        m = self.include_header_re.match(line)
        assert m is not None

        header_title = Text("[")
        header_title.append_text(
            Text(
                f"{self.struct_version}",
                SolarizedColors.Green if self.struct_version == "new" else SolarizedColors.Red
            )
        )
        header_title.append_text(Text(f"] {symbol} - "))
        header_title.append_text(
            Text(
                m.group("header"),
                SolarizedColors.Yellow
            )
        )
        header_title.append(":")
        header_title.append_text(
            Text(
                m.group("line_number"),
                SolarizedColors.Blue
            )
        )
        return header_title

    async def refresh_holes(self, symbol: str) -> None:
        if len(symbol) < 2 or symbol[1] != "#":
            return

        holes_body: HighlightedLog = self.struct_holes.query_one(HighlightedLog)
        holes_header: TitledHeader = self.struct_holes.query_one(TitledHeader)
        cmd = [
            "pahole",
            "-I",
            "-C", symbol[2:],
            self.args.old_vmlinux if self.struct_version == "old" else self.args.new_vmlinux
        ]
        pahole = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await pahole.communicate()
        if pahole.returncode != 0 or stderr:
            stderr = stderr.decode().strip()
            self.notify(
                stderr,
                title="pahole error",
                severity="error"
            )
            return
        holes_body.clear()
        definition_line = None
        for line_number, line in enumerate(stdout.decode().splitlines()):
            if line_number < 2:
                if line_number == 1:
                    definition_line = line
                continue
            holes_body.write_line(line)
        holes_header.set_title(
            self.get_header_title(
                symbol,
                definition_line
            )
        )
