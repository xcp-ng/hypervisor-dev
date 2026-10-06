"""Constants, enums, and color definitions for git-review-rebase."""

from enum import Enum, Flag, StrEnum, auto

from rich.text import Text


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


class CommitMatchInfoFlag(Flag):
    SameCommit = auto()
    LooseMatch = auto()
    MessageChanged = auto()
    PresentInRebaseOnto = auto()
    Dropped = auto()
    Added = auto()
    CleanBackport = auto()
    ModifiedBackport = auto()
    UpstreamNotFound = auto()
    NoCherryPickReference = auto()


REBASE_FLAGS = [
    CommitMatchInfoFlag.SameCommit,
    CommitMatchInfoFlag.LooseMatch,
    CommitMatchInfoFlag.MessageChanged,
    CommitMatchInfoFlag.PresentInRebaseOnto,
    CommitMatchInfoFlag.Dropped,
    CommitMatchInfoFlag.Added,
]

BACKPORT_FLAGS = [
    CommitMatchInfoFlag.CleanBackport,
    CommitMatchInfoFlag.ModifiedBackport,
    CommitMatchInfoFlag.UpstreamNotFound,
    CommitMatchInfoFlag.NoCherryPickReference,
]


class Mode(Enum):
    Rebase = auto()
    Backports = auto()


class CommitMatchInfo:
    def __init__(self, flag, character, definition):
        self.flag = flag
        self.character = character
        self.definition = definition


commit_match_info_repr = {
    CommitMatchInfoFlag.SameCommit: CommitMatchInfo(
        CommitMatchInfoFlag.SameCommit, Text("=", SolarizedColors.Green), "Commits are the same"
    ),
    CommitMatchInfoFlag.LooseMatch: CommitMatchInfo(
        CommitMatchInfoFlag.LooseMatch,
        Text("~", SolarizedColors.Yellow),
        "Commit patchid has changed",
    ),
    CommitMatchInfoFlag.MessageChanged: CommitMatchInfo(
        CommitMatchInfoFlag.MessageChanged,
        Text("✎", SolarizedColors.Orange),
        "Commit message has changed",
    ),
    CommitMatchInfoFlag.PresentInRebaseOnto: CommitMatchInfo(
        CommitMatchInfoFlag.PresentInRebaseOnto,
        Text("⤶", SolarizedColors.Blue),
        "Commit present in new upstream",
    ),
    CommitMatchInfoFlag.Dropped: CommitMatchInfo(
        CommitMatchInfoFlag.Dropped, Text("✗", SolarizedColors.Red), "Commit dropped in rebase"
    ),
    CommitMatchInfoFlag.Added: CommitMatchInfo(
        CommitMatchInfoFlag.Added, Text("✚", SolarizedColors.Green), "Commit added in rebase"
    ),
    CommitMatchInfoFlag.CleanBackport: CommitMatchInfo(
        CommitMatchInfoFlag.CleanBackport,
        Text("=", SolarizedColors.Green),
        "Backport has the same patchid as upstream",
    ),
    CommitMatchInfoFlag.ModifiedBackport: CommitMatchInfo(
        CommitMatchInfoFlag.ModifiedBackport,
        Text("~", SolarizedColors.Yellow),
        "Backport patchid differs from upstream",
    ),
    CommitMatchInfoFlag.UpstreamNotFound: CommitMatchInfo(
        CommitMatchInfoFlag.UpstreamNotFound,
        Text("?", SolarizedColors.Red),
        "Cherry-picked commit not found in the repository",
    ),
    CommitMatchInfoFlag.NoCherryPickReference: CommitMatchInfo(
        CommitMatchInfoFlag.NoCherryPickReference,
        Text("✗", SolarizedColors.Red),
        "No cherry-picked commit in the message",
    ),
}


class FilterType(Enum):
    NoFilter = auto()
    With = auto()
    Without = auto()


class CacheFlags(Flag):
    READ_FROM_CACHE = auto()
    WRITE_TO_CACHE = auto()
