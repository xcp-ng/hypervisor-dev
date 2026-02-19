import argparse
import asyncio
import difflib
import pygit2
import re

from collections import defaultdict

from enum import StrEnum

from pygments.lexer import RegexLexer, bygroups
from pygments.lexers import CLexer
from pygments.token import Token, Text as TokenText, Number

from rich.syntax import Syntax
from rich.text import Text, Span
from rich.style import Style

from textual import work, log
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, LoadingIndicator, Static


from ..fileio import read_lockedlist_grouped
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


class GitLogOnelineLexer(RegexLexer):
    name = "GitLogOneline"
    aliases = ["git-log-oneline"]
    filenames = []

    tokens = {
        "root": [
            (r"([0-9a-f]+)( .+\n?)", bygroups(Token.Literal.Color.Yellow, TokenText)),
        ]
    }


def clear_background(t: Text) -> Text:
    spans = []
    t.style = None
    for span in t.spans:
        if not isinstance(span.style, Style):
            continue
        style = span.style
        spans.append(Span(style=style.color.name, start=span.start, end=span.end))
    t.spans = spans
    return t


class HighlightedLog(VerticalScroll):
    DEFAULT_CSS = """
    HighlightedLog:focus {
        background: $background-lighten-1
}
"""

    def __init__(
        self,
        lexer: None | str = "c",
        theme: None | str = "solarized-dark",
        *args,
        **kwargs,
    ):
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
        self.content.append_text(line)
        self.query_one(Static).content = self.content

    def reset_content(self, content: str):
        self.content = Text("")
        self.content.append_text(clear_background(self.syntax.highlight(content)))
        self.query_one(Static).content = self.content


class TitledVertical(Vertical):
    def __init__(self, *args, **kwargs):
        self.title = kwargs.pop("title") if "title" in kwargs else "unknowntitle"
        super().__init__(*args, **kwargs)

    def compose(self) -> ComposeResult:
        yield TitledHeader(title=self.title)
        yield from super().compose()


class HighlightedTable(DataTable):
    def __init__(
        self,
        lexer: None | str = "c",
        theme: None | str = "solarized-dark",
        *args,
        **kwargs,
    ):
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
    def __init__(self, title: str | Text, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = title

    def set_title(self, title: str | Text) -> None:
        self.title = title
        self.query_one("HeaderTitle").update(self.format_title())

    def format_title(self) -> Content:
        if isinstance(self.title, Text):
            return self.title
        return Text(self.title)


class KabiTuiApp(App):

    DEFAULT_CSS = """
    *:focus {
        scrollbar-color: $primary
    }
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

    BINDINGS = [("n", "toggle_old_new", "Toggle between old/new structs.")]

    loaded: reactive[bool] = reactive(False)

    def __init__(self, args: argparse.Namespace):
        super().__init__()
        self.args = args
        self.repo = pygit2.Repository(args.repository)
        self.struct_version = "old"
        self.differing_types: set[tuple[str, str, str]] = set()

    async def action_toggle_old_new(self) -> None:
        self.struct_version = "old" if self.struct_version == "new" else "new"
        self.refresh_holes_view(self.symbol)

    def start(self) -> None:
        print("App started")
        print(self.args)

    def compose(self) -> ComposeResult:
        self.startup_loading_indicator = LoadingIndicator()
        self.changed_symbols_view = HighlightedTable()
        self.symbol_diff_view = TitledVertical(
            HighlightedLog(lexer="diff"), id="symbol-diff", title="Symbol diff"
        )
        self.struct_holes_view = TitledVertical(HighlightedLog(), title="Holes")
        self.impacted_modules_view = TitledVertical(
            HighlightedLog(), id="impacted-modules", title="Modules impacted"
        )
        self.guilty_commits_view = TitledVertical(
            HighlightedLog(lexer=GitLogOnelineLexer()),
            id="guilty-commits",
            title="Infringuing commits",
        )
        self.body = Horizontal(
            self.changed_symbols_view,
            Vertical(
                Horizontal(
                    Vertical(self.symbol_diff_view, self.impacted_modules_view),
                    self.struct_holes_view,
                    id="main-horizontal",
                ),
                self.guilty_commits_view,
                id="main",
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
        self.changed_symbols_view.styles.width = "20%"

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
        self.symbol = None
        self.old_symtypes = SymTypes.from_file(self.args.symtypes_lhs)
        self.new_symtypes = SymTypes.from_file(self.args.symtypes_rhs)
        self.common_symbols = (
            self.old_symtypes.exports.keys() & self.new_symtypes.exports.keys()
        )
        self.symbol_versions: defaultdict[str, list[tuple[str, str]]] = defaultdict(
            list
        )
        self.rdep_symbol: defaultdict[str, list[str]] = defaultdict(list)
        for symbol in self.common_symbols:
            await asyncio.sleep(0)
            if self.old_symtypes.crc(symbol) == self.new_symtypes.crc(symbol):
                continue
            for sym, old_version, new_version in SymTypes.identify_kabi_difference(
                self.old_symtypes, self.new_symtypes, symbol
            ):
                self.differing_types.add((sym, old_version, new_version))
                self.symbol_versions[sym].append((old_version, new_version))
                self.rdep_symbol[sym].append(symbol)

        for symbol, _, _ in sorted(self.differing_types, key=self.symbol_key):
            self.changed_symbols_view.add_row(
                self.old_symtypes.name(symbol), key=symbol
            )

        self.module_symbols = read_lockedlist_grouped(self.args.locked_file)
        log(self.module_symbols)
        self.loaded = True

    async def on_data_table_row_selected(self, event: DataTable.RowSelected):
        if event.data_table == self.changed_symbols_view:
            if self.symbol == event.row_key.value:
                return
            self.symbol = event.row_key.value
            self.refresh_all()

    @work(exclusive=True)
    async def refresh_all(self) -> None:
        await self.refresh_symbol_data(self.symbol)
        self.refresh_holes_view(self.symbol)
        self.refresh_diff_view(self.symbol)
        self.refresh_modules_view(self.symbol)
        self.refresh_commits_view(self.symbol)

    # /* <3d8c> ./include/linux/mutex.h:53 */
    include_header_re = re.compile(
        r"/[*] <(?P<symver>[a-f0-9]+)> ([.]/)?(?P<header>[^:]+):(?P<line_number>[0-9]+) [*]/"
    )

    def get_header_title(self, symbol: str) -> Text:
        symbol = self.old_symtypes.name(symbol)
        header_title = Text("[")
        header_title.append_text(
            Text(
                f"{self.struct_version}",
                (
                    SolarizedColors.Green
                    if self.struct_version == "new"
                    else SolarizedColors.Red
                ),
            )
        )
        header_title.append_text(Text(f"] {symbol} - "))
        header_title.append_text(Text(self.type_header_file, SolarizedColors.Yellow))
        header_title.append(":")
        header_title.append_text(Text(self.type_line_number, SolarizedColors.Blue))
        return header_title

    async def refresh_symbol_data(self, symbol: str) -> None:
        def refresh_symbol_diff():
            self.old_symbol_definition = self.old_symtypes.gen_short_decl(
                self.symbol_versions[symbol][0][0]
            )
            self.new_symbol_definition = self.new_symtypes.gen_short_decl(
                self.symbol_versions[symbol][0][1]
            )
            self.symbol_diff = [
                diff
                for diff in difflib.unified_diff(
                    self.old_symbol_definition.splitlines(),
                    self.new_symbol_definition.splitlines(),
                    fromfile=self.old_symtypes.name(symbol),
                    tofile=self.new_symtypes.name(symbol),
                    lineterm="",
                )
            ]

        async def refresh_pahole():
            def check(pahole, outputs):
                if pahole.returncode != 0 or outputs[1]:
                    self.notify(
                        outputs[1].decode().strip(),
                        title="pahole error",
                        severity="error",
                    )

            cmd = ["pahole", "-IC", symbol[2:]]
            pahole_old, pahole_new = await asyncio.gather(
                asyncio.create_subprocess_exec(
                    *cmd,
                    self.args.old_vmlinux,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                asyncio.create_subprocess_exec(
                    *cmd,
                    self.args.new_vmlinux,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
            )
            pahole_old_outputs, pahole_new_outputs = await asyncio.gather(
                pahole_old.communicate(), pahole_new.communicate()
            )
            check(pahole_old, pahole_old_outputs)
            check(pahole_new, pahole_new_outputs)
            self.pahole_old_output = pahole_old_outputs[0].decode().splitlines()
            self.pahole_new_output = pahole_new_outputs[0].decode().splitlines()
            header = self.include_header_re.match(self.pahole_old_output[1])
            assert header is not None
            self.type_header_file = header.group("header")
            self.type_line_number = header.group("line_number")

        def refresh_pickaxe():
            clexer = CLexer()
            tokens = []
            for line in self.symbol_diff:
                if line.startswith("+++") or line.startswith("---"):
                    continue
                if not line.startswith("+") and not line.startswith("-"):
                    continue
                tokens = clexer.get_tokens(line)
                tokens = [
                    token_pair[1]
                    for token_pair in tokens
                    if token_pair[0] == Token.Name
                ]
            self.pickaxe_tokens = tokens

        async def refresh_commits():
            if not self.pickaxe_tokens:
                self.commits = []
            cmd = [
                "git",
                "-C",
                self.args.repository,
                "log",
                "--oneline",
                "-G",
                "|".join(self.pickaxe_tokens),
                self.args.rev_list,
                "--",
                self.type_header_file,
            ]
            git_log = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await git_log.communicate()
            if git_log.returncode != 0 or stderr:
                self.notify(
                    stderr.decode().strip(), title="git log error", severity="error"
                )
                self.commits = []
                return
            self.commits = stdout.decode().splitlines()

        def refresh_modules():
            modules = set()
            for orig_symbol in self.rdep_symbol[symbol]:
                for module in self.module_symbols[orig_symbol]:
                    modules.add(module)
            self.modules = modules

        pahole_worker = self.run_worker(refresh_pahole())
        refresh_symbol_diff()
        refresh_pickaxe()
        refresh_modules()
        await pahole_worker.wait()
        await refresh_commits()

    def refresh_diff_view(self, symbol: str) -> None:
        diff_body: HighlightedLog = self.symbol_diff_view.query_one(HighlightedLog)
        diff_body.reset_content("\n".join(self.symbol_diff))

    def refresh_commits_view(self, symbol: str) -> None:
        commits_body: HighlightedLog = self.guilty_commits_view.query_one(
            HighlightedLog
        )
        commits_body.reset_content("\n".join(self.commits))

    def refresh_modules_view(self, symbol: str) -> None:
        modules_body: HighlightedLog = self.impacted_modules_view.query_one(
            HighlightedLog
        )

        modules_body.reset_content("\n".join(sorted(self.modules)))

    def refresh_holes_view(self, symbol: str) -> None:
        if len(symbol) < 2 or symbol[1] != "#":
            return

        pahole_output = (
            self.pahole_new_output
            if self.struct_version == "new"
            else self.pahole_old_output
        )

        holes_body: HighlightedLog = self.struct_holes_view.query_one(HighlightedLog)
        holes_body.reset_content("\n".join(pahole_output[2:]))

        holes_header: TitledHeader = self.struct_holes_view.query_one(TitledHeader)
        holes_header.set_title(self.get_header_title(symbol))
