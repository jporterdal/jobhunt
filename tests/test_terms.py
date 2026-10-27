"""The "Taught <Term> <Year>, ..." rule (enrich/terms.py)."""

import pytest

from jobhunt.enrich.terms import terms


def dates(line):
    found = terms(line)
    return None if found is None else [(t.start, t.end) for t in found]


def test_four_terms():
    assert dates("Taught Fall 2026, Winter 2026, Winter 2025, Winter 2024") == [
        ("2026-09", "2026-12"), ("2026-01", "2026-04"), ("2025-01", "2025-04"), ("2024-01", "2024-04"),
    ]


def test_terms_joined_by_and():
    assert dates("Taught Summer 2017 and Summer 2016") == [("2017-05", "2017-08"), ("2016-05", "2016-08")]


def test_one_term_and_seasons_named():
    [term] = terms("Taught Winter 2025")
    assert (term.season, term.year, term.start, term.end) == ("Winter", "2025", "2025-01", "2025-04")


def test_spacing_case_and_a_final_full_stop():
    assert dates("  taught  fall 2020 ,  winter 2021, and summer 2021. ") == [
        ("2020-09", "2020-12"), ("2021-01", "2021-04"), ("2021-05", "2021-08"),
    ]


@pytest.mark.parametrize("line", [
    "Taught core courses",
    "Spring 2020",
    "Taught Spring 2020",
    "Taught Fall 2026 to first-year students",
    "Fall 2026, Winter 2026",
    "Taught Fall 26",
])
def test_lines_that_are_not_terms(line):
    assert terms(line) is None
