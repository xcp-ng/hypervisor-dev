import argparse
import asyncio
import difflib
import re
from collections import defaultdict
from subprocess import CalledProcessError

from pygments.lexer import Lexer, RegexLexer, bygroups
from pygments.lexers import CLexer
from pygments.styles.solarized import SolarizedDarkStyle
from pygments.token import Number, Token
from pygments.token import Text as TokenText
from rich.style import Style
from rich.syntax import Syntax, SyntaxTheme
from rich.text import Span, Text
from textual import log, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.content import Content
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, LoadingIndicator, Static
from textual.worker import Worker, WorkerFailed

from ..fileio import read_lockedlist_grouped
from ..symtypes import SymTypes


class GitStyle(SolarizedDarkStyle):
    from pygments.styles.solarized import DARK_COLORS

    styles = {Number.Hex: DARK_COLORS["yellow"], TokenText: DARK_COLORS["base0"]}


class GitLogOnelineLexer(RegexLexer):
    name = "GitLogOneline"
    aliases = ["git-log-oneline"]

    tokens = {
        "root": [
            (r"([0-9a-f]+)( .+\n?)", bygroups(Number.Hex, TokenText)),
        ]
    }


def clear_background(t: Text) -> Text:
    spans = []
    t.style = ""
    for span in t.spans:
        if not isinstance(span.style, Style):
            continue
        style = span.style
        color_name = style.color.name if style.color is not None else "default"
        spans.append(Span(style=color_name, start=span.start, end=span.end))
    t.spans = spans
    return t


class HighlightedLog(ScrollableContainer):
    DEFAULT_CSS = """

    HighlightedLog:focus {
        background: $background-lighten-1
}
"""

    def __init__(
        self,
        lexer: str | Lexer = "c",
        theme: str | SyntaxTheme = "solarized-dark",
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
        line_text = clear_background(self.syntax.highlight(line))
        self.content.append_text(line_text)
        self.query_one(Static).content = self.content

    def reset_content(self, content: str):
        self.content = Text("")
        self.content.append_text(clear_background(self.syntax.highlight(content)))
        self.query_one(Static).content = self.content

    def _update_focusability(self) -> None:
        self.can_focus = self.max_scroll_y > 0

    def watch_virtual_size(self, virtual_size) -> None:
        self._update_focusability()

    def on_resize(self) -> None:
        self._update_focusability()

    def scroll_page_down(self, *args, **kwargs) -> None:
        kwargs.setdefault("animate", False)
        super().scroll_page_down(*args, **kwargs)

    def scroll_page_up(self, *args, **kwargs) -> None:
        kwargs.setdefault("animate", False)
        super().scroll_page_up(*args, **kwargs)


class TitledVertical(Vertical):
    def __init__(self, *args, **kwargs):
        self.title = kwargs.pop("title") if "title" in kwargs else "unknowntitle"
        super().__init__(*args, **kwargs)

    def compose(self) -> ComposeResult:
        yield TitledHeader(title=self.title, classes="titled-header")
        yield from super().compose()

    def on_descendant_focus(self, event) -> None:
        """Update header when a descendant gets focus"""
        self._update_header_focus()

    def on_descendant_blur(self, event) -> None:
        """Update header when a descendant loses focus"""
        self._update_header_focus()

    def _update_header_focus(self) -> None:
        """Check if any descendant has focus and update header accordingly"""
        header = self.query_one(TitledHeader)
        # Check if any child (other than the header) has focus
        focused = self.screen.focused
        if focused is not None and focused is not header:
            # Walk up from focused widget to see if it's under this container
            node = focused
            while node is not None:
                if node is self:
                    header.has_descendant_focus = True
                    return
                node = node._parent  # type: ignore[assignment]
        header.has_descendant_focus = False


class HighlightedTable(DataTable):
    DEFAULT_CSS = """
    HighlightedTable {
        &:focus {
            & > .datatable--cursor {
                background: $block-hover-background;
            }
        }
    }
"""

    def __init__(
        self,
        lexer: str | Lexer = "c",
        theme: str | SyntaxTheme = "solarized-dark",
        column_titles: None | list[str] = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, cursor_foreground_priority="renderable", **kwargs)
        self.syntax = Syntax(
            "",
            lexer=lexer,
            theme=theme,
            background_color="default",
        )
        self.column_titles = column_titles if column_titles is not None else []

    def on_mount(self) -> None:
        self.cursor_type = "row"
        for title in self.column_titles:
            self.add_column(title)

    def add_line(self, line, *args, **kwargs):
        line = self.syntax.highlight(line)
        super().add_row(clear_background(line), *args, **kwargs)


class HighlightedCommitsTable(HighlightedTable):
    BINDINGS = [("enter", "git_show", "Show commit")]

    def add_line(self, line, *args, **kwargs):
        commit_sha1 = line.split(" ")[0]
        super().add_line(line, *args, key=commit_sha1, **kwargs)

    def action_git_show(self):
        self.action_select_cursor()


class TitledHeader(Header):
    has_descendant_focus: reactive[bool] = reactive(False)

    DEFAULT_CSS = """
    TitledHeader.has-focus-within {
        background: $block-cursor-blurred-background;
    }
    """

    def __init__(self, title: str | Text, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = title

    def set_title(self, title: str | Text) -> None:
        self.title = title
        header_title: Static = self.query_exactly_one("HeaderTitle")  # type: ignore[assignment]
        header_title.update(self.format_title())

    def format_title(self) -> Content:
        return Content.from_text(self.title)

    def watch_has_descendant_focus(self, value: bool) -> None:
        self.set_class(value, "has-focus-within")


class CommitShowScreen(ModalScreen):
    CSS = """
    CommitShowScreen {
        align: center middle;
    }

    #dialog {
        background: $panel;
        border: round $primary;
        width: 90%;
        height: 90%;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("q", "close", "Close"),
        Binding("W", "toggle_function_context", "Toggle function context"),
        Binding("]", "increase_context", "Increase context"),
        Binding("[", "decrease_context", "Decrease context"),
        Binding("escape", "close", "Close", show=False),
    ]

    loaded: reactive[bool] = reactive(False)

    def __init__(self, repository: str, commit_sha1: str, title: Text, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.commit_sha1 = commit_sha1
        self.repository = repository
        self.context = 3
        self.function_context: bool = False
        self.header_title = title

    def action_close(self) -> None:
        self.dismiss(None)

    def action_toggle_function_context(self) -> None:
        self.function_context = not self.function_context
        body: HighlightedLog = self.vertical.query_one(HighlightedLog)
        body.scroll_home(animate=False)
        self.loaded = False
        self.load_commit_show()

    def action_increase_context(self) -> None:
        self.context += 1
        self.loaded = False
        self.load_commit_show()

    def action_decrease_context(self) -> None:
        orig_context = self.context
        self.context = max(0, self.context - 1)
        if orig_context != self.context:
            self.loaded = False
            self.load_commit_show()

    @work
    async def load_commit_show(self) -> None:
        cmd = ["git", "-C", self.repository, "show", f"-U{self.context}"]
        if self.function_context:
            cmd.append("-W")
        cmd.append(self.commit_sha1)
        git_show = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await git_show.communicate()
        if git_show.returncode != 0 or stderr:
            self.app.notify(stderr.decode(), title="git show error", severity="error")
            return
        self.content = stdout.decode()
        body: HighlightedLog = self.vertical.query_one(HighlightedLog)
        body.reset_content(self.content)
        self.loaded = True

    def watch_loaded(self, loaded: bool) -> None:
        body: HighlightedLog = self.vertical.query_one(HighlightedLog)
        if loaded:
            self.loading_indicator.display = False
            body.display = True
            body.focus()
        else:
            self.loading_indicator.display = True
            body.display = False

    def compose(self) -> ComposeResult:
        self.loading_indicator = LoadingIndicator()
        yield self.loading_indicator
        self.vertical = TitledVertical(
            HighlightedLog(
                lexer="diff",
            ),
            title=self.header_title,
            id="dialog",
        )
        yield self.vertical
        yield Footer()

    def on_mount(self) -> None:
        self.loading_indicator.display = True
        body = self.vertical.query_one(HighlightedLog)
        body.display = False
        self.load_commit_show()


class WorkerCalledProcessError(CalledProcessError):
    pass


# @dataclass
# class PaholeInfo:
#     output: list[str]
#     definition_file: str
#     definition_line: str

# class TypeInfo:
#     def __init__(self):
#         self.old_pahole_info: PaholeInfo | None = None
#         self.new_pahole_info: PaholeInfo | None = None


class KabiTuiApp(App):
    DEFAULT_CSS = """
    *:focus {
        scrollbar-color: $primary;
    }
    CSymbolTable > {
        height: 100%;
    }
    #main {
        width: 1fr;
    }
    #main-horizontal {
        height: 5fr;
    }
    #guilty-commits  {
        height: 1fr;
    }
    #holes {
        width: 5fr;
    }
    #impacted-modules {
        height: 1fr;
    }
    #diff-side {
        width: 4fr;
    }
    #symbol-diff {
        height: 4fr;
    }
    """

    BINDINGS = [
        ("n", "toggle_old_new", "Toggle between old/new structs"),
        ("q", "action_quit", "Quit"),
        ("v", "toggle_verbose", "Toggle verbose pahole output"),
    ]

    loaded: reactive[bool] = reactive(False)

    def __init__(self, args: argparse.Namespace):
        super().__init__()
        self.args = args
        self.struct_version = "old"
        self.verbose_pahole = True
        self.differing_types: set[tuple[str, str, str]] = set()

        self.pahole_worker: None | Worker = None

        # Valid for currently selected type (likely to go in its own dataclass)
        self.type_name: None | str = None
        self.modules: set[str] = set()
        self.commits: list[str] = []

    def action_toggle_old_new(self) -> None:
        self.struct_version = "old" if self.struct_version == "new" else "new"
        self.refresh_holes_view()

    def action_toggle_verbose(self) -> None:
        self.verbose_pahole = not self.verbose_pahole
        self.pahole_worker = self.reload_pahole_data()
        self.refresh_holes_view()

    def compose(self) -> ComposeResult:
        self.startup_loading_indicator = LoadingIndicator()
        self.changed_symbols_view = TitledVertical(
            HighlightedTable(column_titles=[""], show_header=False), title="Changed symbols"
        )
        self.symbol_diff_view = TitledVertical(
            HighlightedLog(lexer="diff"), id="symbol-diff", title="Symbol diff"
        )
        self.struct_holes_view = TitledVertical(HighlightedLog(), title="Holes", id="holes")
        self.impacted_symbols_view = TitledVertical(
            HighlightedLog(), id="impacted-symbols", title="Symbols impacted"
        )
        self.impacted_modules_view = TitledVertical(
            HighlightedLog(), id="impacted-modules", title="Modules impacted"
        )
        self.guilty_commits_view = TitledVertical(
            HighlightedCommitsTable(
                lexer=GitLogOnelineLexer(),
                theme=GitStyle,  # type: ignore[arg-type]
                column_titles=[""],
                show_header=False,
            ),
            id="guilty-commits",
            title="Infringuing commits",
        )
        self.body = Horizontal(
            self.changed_symbols_view,
            Vertical(
                Horizontal(
                    Vertical(self.symbol_diff_view, self.impacted_modules_view, id="diff-side"),
                    self.struct_holes_view,
                    id="main-horizontal",
                ),
                self.impacted_symbols_view,
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
        self.load_kabi_data()

    def watch_loaded(self, loaded: bool) -> None:
        if loaded:
            self.startup_loading_indicator.display = False
            self.body.display = True

    def symbol_key(self, key):
        symbol = key[0]
        if len(symbol) > 2 and symbol[1] == "#":
            return "." + symbol
        return symbol

    @work(thread=True)
    async def load_kabi_data(self) -> None:
        self.type_name = None
        self.old_symtypes = SymTypes.from_file(self.args.symtypes_lhs)
        self.new_symtypes = SymTypes.from_file(self.args.symtypes_rhs)
        self.common_symbols = self.old_symtypes.exports.keys() & self.new_symtypes.exports.keys()
        self.symbol_versions: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
        self.rdep_symbol: defaultdict[str, list[str]] = defaultdict(list)
        for symbol in self.common_symbols:
            if self.old_symtypes.crc(symbol) == self.new_symtypes.crc(symbol):
                continue
            self.symbol_versions[symbol].append(
                (
                    self.old_symtypes.versioned(symbol, self.old_symtypes.exports[symbol]),
                    self.new_symtypes.versioned(symbol, self.new_symtypes.exports[symbol]),
                )
            )
            for sym, old_version, new_version in SymTypes.identify_kabi_difference(
                self.old_symtypes, self.new_symtypes, symbol
            ):
                self.differing_types.add((sym, old_version, new_version))
                self.symbol_versions[sym].append((old_version, new_version))
                self.rdep_symbol[sym].append(symbol)

        changed_symbols_body = self.changed_symbols_view.query_one(HighlightedTable)
        for symbol, _, _ in sorted(self.differing_types, key=self.symbol_key):
            changed_symbols_body.add_line(self.old_symtypes.name(symbol), key=symbol)

        self.module_symbols = read_lockedlist_grouped(self.args.locked_file)
        log(self.module_symbols)
        self.loaded = True

    async def on_data_table_row_selected(self, event: DataTable.RowSelected):
        changed_symbols_body: HighlightedTable = self.changed_symbols_view.query_one(
            HighlightedTable
        )
        if event.data_table == changed_symbols_body:
            if self.type_name == event.row_key.value:
                return
            self.type_name = event.row_key.value
            self.refresh_all()
            return
        commits_table: HighlightedCommitsTable = self.guilty_commits_view.query_one(
            HighlightedCommitsTable
        )
        if event.data_table == commits_table:
            assert event.row_key.value is not None
            self.display_commit(event.row_key.value, commits_table.get_row(event.row_key)[0])

    def display_commit(self, commit_sha1: str, commit_oneline: Text):
        self.push_screen(CommitShowScreen(self.args.repository, commit_sha1, commit_oneline))

    @work(exclusive=True)
    async def refresh_all(self) -> None:
        await self.reload_type_info()
        self.refresh_holes_view()
        self.refresh_diff_view()
        self.refresh_modules_view()
        self.refresh_commits_view()
        self.refresh_symbols_view()

    # /* <3d8c> ./include/linux/mutex.h:53 */
    include_header_re = re.compile(
        r"/[*] <(?P<symver>[a-f0-9]+)> ([.]/)?(?P<header>[^:]+):(?P<line_number>[0-9]+) [*]/"
    )

    @work(exclusive=True, thread=True, exit_on_error=False)
    async def reload_pahole_data(self):
        def clear_pahole_data():
            self.pahole_old_output = []
            self.pahole_new_output = []
            self.definition_file = "unknown"

        def check(pahole, outputs, vmlinux):
            if pahole.returncode != 0 or outputs[1]:
                self.notify(
                    outputs[1].decode().strip(),
                    title="pahole error",
                    severity="error",
                )
                clear_pahole_data()
                raise WorkerCalledProcessError(
                    pahole.returncode, cmd + [vmlinux], output=outputs[0], stderr=outputs[1]
                )

        assert self.type_name is not None
        # We run pahole for enums, structs, typedefs and unions
        if not (
            self.type_name.startswith("e#")
            or self.type_name.startswith("s#")
            or self.type_name.startswith("t#")
            or self.type_name.startswith("u#")
        ):
            clear_pahole_data()
            return

        cmd = ["pahole", "-I"]
        if not self.verbose_pahole:
            cmd.append("--quiet")
        cmd.extend(["-C", self.type_name[2:]])
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
        check(pahole_old, pahole_old_outputs, self.args.old_vmlinux)
        check(pahole_new, pahole_new_outputs, self.args.new_vmlinux)
        self.pahole_old_output = pahole_old_outputs[0].decode().splitlines()
        self.pahole_new_output = pahole_new_outputs[0].decode().splitlines()
        header_match = self.include_header_re.match(self.pahole_old_output[1])
        assert header_match is not None
        self.definition_file = header_match.group("header")

    def get_header_title(self, type_name: str) -> Text:
        expanded_type_name = clear_background(
            Syntax("", lexer="c", theme=self.theme, background_color="default").highlight(
                self.new_symtypes.name(type_name)
                if self.struct_version == "new"
                else self.old_symtypes.name(type_name)
            )
        )
        expanded_type_name.rstrip()
        header_title = Text("")
        header_title.append_text(
            Text(
                f"[{self.struct_version}] ",
                (
                    self.theme_variables["success"]
                    if self.struct_version == "new"
                    else self.theme_variables["error"]
                ),
            )
        )
        header_title.append_text(expanded_type_name)
        header_title.append_text(Text(" - "))
        header_title.append_text(Text(self.definition_file, self.theme_variables["accent"]))
        log(f"{header_title=} {self.new_symtypes.name(type_name)=}")
        return header_title

    def reload_type_diff(self):
        assert self.type_name is not None
        self.old_symbol_definition = self.old_symtypes.gen_short_decl(
            self.symbol_versions[self.type_name][0][0]
        )
        self.new_symbol_definition = self.new_symtypes.gen_short_decl(
            self.symbol_versions[self.type_name][0][1]
        )
        self.symbol_diff = list(
            difflib.unified_diff(
                self.old_symbol_definition.splitlines(),
                self.new_symbol_definition.splitlines(),
                fromfile=self.old_symtypes.name(self.type_name),
                tofile=self.new_symtypes.name(self.type_name),
                lineterm="",
            )
        )

    def reload_pickaxe_tokens(self):
        assert self.type_name is not None
        if (
            self.type_name.startswith("s#")
            or self.type_name.startswith("e#")
            or self.type_name.startswith("t#")
            or self.type_name.startswith("u#")
        ):
            clexer = CLexer()
            tokens = []
            for line in self.symbol_diff:
                if line.startswith("+++") or line.startswith("---"):
                    continue
                if not line.startswith("+") and not line.startswith("-"):
                    continue
                tokens.extend(
                    [
                        token_pair[1]
                        for token_pair in clexer.get_tokens(line)
                        if token_pair[0] == Token.Name
                    ]
                )
            self.pickaxe_tokens = tokens
        elif self.type_name.startswith("(") and self.type_name.endswith(")"):
            self.pickaxe_tokens = [self.type_name[1:-1]]
        else:
            self.pickaxe_tokens = []

    async def reload_commits(self):
        def git_cmd_from_tokens():
            if not self.pickaxe_tokens or self.definition_file == "unknown":
                return None
            cmd = [
                "git",
                "-C",
                self.args.repository,
                "log",
                "--oneline",
                "--no-decorate",
                "-G",
                "(" + "|".join(self.pickaxe_tokens) + ")",
                self.args.rev_list,
                "--",
                self.definition_file,
            ]
            return cmd

        def git_cmd_from_header_addition():
            # We have a struct that was only forward declared that has
            # become fully defined for some symbols.  So here we identify
            # which files those symbols live in, and try to get the list of
            # commits that added a header file to those same files.
            #
            # It may seem that we can use self.definition_file instead of
            # matching with all "#include", but often the header file being
            # included is not necessarily the one containing the definition
            # of the symbol, but another header file including it.
            #
            # So make the choice to have more false positives here, rather
            # than missing the guilty commits as a human should be able to
            # tell easily if there are more than one match.
            cmd = [
                "git",
                "-C",
                self.args.repository,
                "log",
                "--oneline",
                "--no-decorate",
                "-G",
                "#include",
                self.args.rev_list,
                "--",
            ]
            filenames = set()
            assert self.type_name is not None
            for rdep_symbol in self.rdep_symbol[self.type_name]:
                filenames.add(self.old_symtypes.exports[rdep_symbol].replace(".symtypes", ".c"))
            cmd.extend(filenames)
            log(f"{cmd=}")
            return cmd

        if "UNKNOWN" in self.old_symbol_definition or "UNKOWN" in self.new_symbol_definition:
            cmd = git_cmd_from_header_addition()
        else:
            cmd = git_cmd_from_tokens()

        if cmd is None:
            self.commits = []
            return

        git_log = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await git_log.communicate()
        if git_log.returncode != 0 or stderr:
            self.notify(stderr.decode().strip(), title="git log error", severity="error")
            self.commits = []
            return
        self.commits = stdout.decode().splitlines()

    def reload_modules_data(self):
        assert self.type_name is not None
        modules: set[str] = set()
        for orig_symbol in self.rdep_symbol[self.type_name]:
            for module in self.module_symbols[orig_symbol]:
                modules.add(module)
        self.modules = modules

    async def reload_type_info(self) -> None:

        pahole_worker = self.reload_pahole_data()

        self.reload_type_diff()
        self.reload_pickaxe_tokens()
        self.reload_modules_data()

        try:
            await pahole_worker.wait()
        except WorkerFailed:
            pass

        await self.reload_commits()

    def refresh_diff_view(self) -> None:
        diff_body: HighlightedLog = self.symbol_diff_view.query_one(HighlightedLog)
        diff_body.reset_content("\n".join(self.symbol_diff))

    def refresh_commits_view(self) -> None:
        commits_body: HighlightedTable = self.guilty_commits_view.query_one(HighlightedTable)
        commits_body.clear()
        for line in self.commits:
            commits_body.add_line(line.strip())

    def refresh_symbols_view(self) -> None:
        symbols_body: HighlightedLog = self.impacted_symbols_view.query_one(HighlightedLog)
        symbols: set[str] = set()
        assert self.type_name is not None
        for rdep_symbol in self.rdep_symbol[self.type_name]:
            symbol_versions = self.symbol_versions[rdep_symbol]
            assert symbol_versions is not None
            symbols.add(self.old_symtypes.gen_short_decl(symbol_versions[0][0]))
        symbols_body.reset_content("\n".join(sorted(symbols)))

    def refresh_modules_view(self) -> None:
        modules_body: HighlightedLog = self.impacted_modules_view.query_one(HighlightedLog)

        modules_body.reset_content("\n".join(sorted(self.modules)))

    @work
    async def refresh_holes_view(self) -> None:
        assert self.type_name is not None
        if len(self.type_name) < 2 or self.type_name[1] != "#":
            return

        if self.pahole_worker is not None:
            try:
                await self.pahole_worker.wait()
            except WorkerFailed:
                return
            finally:
                self.pahole_worker = None

        pahole_output = (
            self.pahole_new_output if self.struct_version == "new" else self.pahole_old_output
        )

        holes_body: HighlightedLog = self.struct_holes_view.query_one(HighlightedLog)
        holes_body.reset_content("\n".join(pahole_output[2:]))

        holes_header: TitledHeader = self.struct_holes_view.query_one(TitledHeader)
        holes_header.set_title(self.get_header_title(self.type_name))
