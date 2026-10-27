from dataclasses import dataclass

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
