from dataclasses import dataclass
from pathlib import Path

from jobhunt import parsers
from jobhunt.parsers.posting_file import PARSER, PostingFileParser

from .fakes import FakeParser

FAKES = {"alpha": FakeParser("alpha"), "beta": FakeParser("beta"), "alpha-again": FakeParser("alpha")}


@dataclass
class Point:
    """An entry point stand-in: `value` names an object in FAKES, or 'boom' to fail on load."""

    name: str
    value: str

    def load(self):
        if self.value == "boom":
            raise ImportError("no module named 'missing'")
        if self.value == "class":
            return PostingFileParser
        if self.value == "junk":
            return object()
        return FAKES[self.value]


def test_loads_entry_points_sorted_by_name():
    loaded = parsers.load([Point("b", "beta"), Point("a", "alpha")])
    assert [p.name for p in loaded.parsers] == ["alpha", "beta"]
    assert loaded.errors == ()


def test_a_class_is_instantiated():
    loaded = parsers.load([Point("posting-file", "class")])
    assert isinstance(loaded.parsers[0], PostingFileParser)


def test_duplicate_names_are_refused():
    loaded = parsers.load([Point("a", "alpha"), Point("a2", "alpha-again"), Point("b", "beta")])
    assert [p.name for p in loaded.parsers] == ["beta"]
    assert len(loaded.errors) == 1 and "'alpha'" in loaded.errors[0]


def test_failing_entry_point_is_reported_and_the_rest_load():
    loaded = parsers.load([Point("broken", "boom"), Point("b", "beta"), Point("odd", "junk")])
    assert [p.name for p in loaded.parsers] == ["beta"]
    assert len(loaded.errors) == 2
    assert "'broken'" in loaded.errors[0] and "ImportError" in loaded.errors[0]
    assert "'odd'" in loaded.errors[1] and "not a parser" in loaded.errors[1]


def test_installed_lists_the_built_in_parser():
    installed = parsers.installed()
    assert PARSER in installed.parsers
    assert parsers.label(PARSER) == "posting-file@1"


class Marking(FakeParser):
    """A parser whose `discardable` answers with `marks` (paths relative to the file's folder)."""

    def __init__(self, companions_=(), marks=(), boom=None):
        super().__init__("marking")
        self.names, self.marks, self.boom = companions_, marks, boom

    def companions(self, path):
        if self.boom == "companions":
            raise OSError("cannot list")
        return [path.with_name(n) for n in self.names]

    def discardable(self, path):
        if self.boom == "discardable":
            raise ValueError("broken")
        return [path.with_name(n) for n in self.marks]


PAGE = Path("inbox/page.html")


def test_a_parser_marks_its_asset_folder():
    parser = FakeParser(companion_suffixes=("_files", ".meta"), discardable_suffixes=("_files",))
    assert parsers.discardable(parser, PAGE) == [Path("inbox/page_files")]


def test_a_path_that_isnt_the_parsers_companion_is_not_discardable():
    parser = Marking(companions_=["page_files"], marks=["other.html", "page_files"])
    assert parsers.discardable(parser, PAGE) == [Path("inbox/page_files")]


def test_download_metadata_and_the_file_itself_are_never_discardable():
    names = ["page.html:Zone.Identifier", "page.html"]
    assert parsers.discardable(Marking(companions_=names, marks=names), PAGE) == []


def test_a_raising_parser_marks_nothing():
    assert parsers.discardable(Marking(["page_files"], ["page_files"], boom="discardable"), PAGE) == []
    assert parsers.discardable(Marking(["page_files"], ["page_files"], boom="companions"), PAGE) == []


def test_a_parser_without_the_method_marks_nothing():
    class Plain:
        name, version = "plain", "1"

        def parse(self, file):
            return None

        def companions(self, path):
            return [path.with_name("page_files")]

    assert parsers.discardable(Plain(), PAGE) == []
    assert parsers.discardable(PARSER, PAGE) == []  # the built-in parser has no companions
