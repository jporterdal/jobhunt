"""Compare two stages of the MCP measurement (docs/mcp-eval.md): per question, the pass counts of both, the observed
direction, the difference in pass rate with a 95% interval, and a one-sided mid-p value; no verdict.

    venv/bin/python scripts/mcp_eval/compare.py data/mcp-eval/stages/CURRENT data/mcp-eval/stages/CANDIDATE [--json]
    venv/bin/python scripts/mcp_eval/compare.py --conditions data/mcp-eval/stages/A data/mcp-eval/stages/B [--json]

The first stage is the current code, the second the candidate. For each question: the direction (`more` when the
second stage's pass rate is higher, `fewer` when lower, `same` when equal), the difference (second minus first) with
a 95% Newcombe hybrid score interval (from the two Wilson intervals; left out, and said so, when both stages passed or
both failed every sample), and the mid-p value for the observed direction: with the a + b passes of n + m samples
shared at random (the hypergeometric distribution), the chance of a split further that way than observed plus half
the chance of the observed one. The two directions' mid-p values add to 1 (`same`: 0.5 each). Nothing is compared
with a threshold: the figures are evidence for the user, who decides adoption (the `mcp-evaluation` spec). The set
line counts the questions in each direction.

Stages of different sets, models, kinds, history conditions or orders are refused (exit 2). Equal code hashes and
different Ollama versions are warned about. Held-out questions are shown as counts and the figures computed from them,
never their transcripts.

`--conditions A B` compares two stages of the same code (equal code hashes), set, model and kind that differ in
history condition or order, with the same figures per question (`more`: B passes more often). It attributes a
difference to the history (or order) and decides nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from math import comb, sqrt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
import score  # noqa: E402

Z = 1.959963984540054  # the standard normal's 97.5th percentile: 95% intervals


def _hypergeometric(a: int, n: int, b: int, m: int) -> dict[int, float]:
    """With the a + b passes of n + m samples shared at random, the chance of each pass count in the second stage."""
    passes, total = a + b, n + m
    lo, hi = max(0, m - (total - passes)), min(passes, m)
    return {x: comb(passes, x) * comb(total - passes, m - x) / comb(total, m) for x in range(lo, hi + 1)}


def p_more(a: int, n: int, b: int, m: int) -> float:
    """One-sided Fisher exact test: the probability, with the a + b passes of n + m samples shared at random, that
    the second stage's m samples hold b passes or more."""
    return sum(p for x, p in _hypergeometric(a, n, b, m).items() if x >= b)


def p_less(a: int, n: int, b: int, m: int) -> float:
    """The same for b passes or fewer."""
    return sum(p for x, p in _hypergeometric(a, n, b, m).items() if x <= b)


def mid_p_more(a: int, n: int, b: int, m: int) -> float:
    """One-sided mid-p for "the second stage passes more often": more than b passes, plus half of exactly b."""
    return p_more(a, n, b, m) - _hypergeometric(a, n, b, m)[b] / 2


def mid_p_fewer(a: int, n: int, b: int, m: int) -> float:
    """The same for "fewer": fewer than b passes, plus half of exactly b. mid_p_more + mid_p_fewer == 1."""
    return p_less(a, n, b, m) - _hypergeometric(a, n, b, m)[b] / 2


def wilson(x: int, n: int) -> tuple[float, float]:
    """The 95% Wilson score interval for x passes of n samples."""
    p = x / n
    scale = 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / scale
    half = Z * sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / scale
    return max(0.0, centre - half), min(1.0, centre + half)


def difference(a: int, n: int, b: int, m: int) -> tuple[float, float, float]:
    """The second stage's pass rate minus the first's, with its 95% Newcombe hybrid score interval."""
    p1, p2 = a / n, b / m
    (l1, u1), (l2, u2) = wilson(a, n), wilson(b, m)
    d = p2 - p1
    return d, d - sqrt((p2 - l2) ** 2 + (u1 - p1) ** 2), d + sqrt((u2 - p2) ** 2 + (p1 - l1) ** 2)


def direction(a: int, n: int, b: int, m: int) -> str:
    """`more`, `fewer` or `same`: the second stage's pass rate against the first's (the counts, at equal samples)."""
    return "more" if b * n > a * m else "fewer" if b * n < a * m else "same"


def figures(a: int, n: int, b: int, m: int) -> dict:
    """One question's figures: direction, difference, interval (None when both stages passed, or both failed, every
    sample: `all_same` says which), and both directions' mid-p values, to four places."""
    if not n or not m:
        return {"direction": None, "difference": None, "interval": None, "all_same": None,
                "mid_p_more": None, "mid_p_fewer": None}
    word = direction(a, n, b, m)
    d, lo, hi = difference(a, n, b, m)
    all_same = "passed" if a == n and b == m else "failed" if a == b == 0 else None
    more, fewer = (0.5, 0.5) if word == "same" else (mid_p_more(a, n, b, m), mid_p_fewer(a, n, b, m))
    return {"direction": word, "difference": round(d, 4),
            "interval": None if all_same else [round(lo, 4), round(hi, 4)], "all_same": all_same,
            "mid_p_more": round(more, 4), "mid_p_fewer": round(fewer, 4)}


def directions(rows: dict) -> dict[str, int]:
    """The set's questions in each direction."""
    return {word: sum(row["direction"] == word for row in rows.values()) for word in ("more", "fewer", "same")}


def compare(first: dict, second: dict) -> dict:
    """Two scored stages (score.score_stage) and their stage.json descriptions, compared."""
    questions = [qid for qid in first["questions"] if qid in second["questions"]]
    rows = {}
    for qid in questions:
        a, n = first["questions"][qid]["passed"], first["questions"][qid]["samples"]
        b, m = second["questions"][qid]["passed"], second["questions"][qid]["samples"]
        rows[qid] = {"current": [a, n], "candidate": [b, m], **figures(a, n, b, m)}
    only = sorted(set(first["questions"]) ^ set(second["questions"]))
    return {"current": first["stage"], "candidate": second["stage"], "set": first["set"], "kind": first["kind"],
            "model": first["model"], "history": condition(first)["history"], "order": condition(first)["order"],
            "questions": rows, "not_compared": only, "directions": directions(rows)}


def refusal(first_info: dict, second_info: dict) -> str | None:
    for key, what in (("set", "sets"), ("kind", "kinds"), ("model", "models")):
        if first_info.get(key) != second_info.get(key):
            return (f"the stages are of different {what} ({first_info.get(key)} and {second_info.get(key)}); "
                    "only stages of one set, kind and model are compared")
    first, second = common.conditions(first_info), common.conditions(second_info)
    for key, what in (("history", "history conditions"), ("order", "orders")):
        if first[key] != second[key]:
            return (f"the stages have different {what} ({first[key]} and {second[key]}); code versions are compared "
                    "under one condition (compare conditions of the same code with --conditions)")
    return None


def conditions_refusal(first_info: dict, second_info: dict) -> str | None:
    """Why two stages can't be compared as conditions: different code, set, model or kind, or the same condition."""
    if not first_info.get("code_sha256") or first_info.get("code_sha256") != second_info.get("code_sha256"):
        return ("the stages ran different code (code hashes differ); --conditions compares conditions of one code "
                "version (compare code versions without it)")
    for key, what in (("set", "sets"), ("kind", "kinds"), ("model", "models")):
        if first_info.get(key) != second_info.get(key):
            return (f"the stages are of different {what} ({first_info.get(key)} and {second_info.get(key)}); "
                    "conditions are compared on one set, kind and model")
    first, second = common.conditions(first_info), common.conditions(second_info)
    if (first["history"], first["order"]) == (second["history"], second["order"]):
        return (f"both stages ran {common.condition_label(first_info)}; --conditions compares stages whose history "
                "or order differ")
    return None


def compare_conditions(first: dict, second: dict) -> dict:
    """Two scored stages of one code version under different conditions: per question both pass counts and the same
    figures as compare() (`more`: the second passes more often)."""
    result = compare(first, second)
    rows = {qid: {"first": row.pop("current"), "second": row.pop("candidate"), **row}
            for qid, row in result["questions"].items()}
    return {"first": first["stage"], "second": second["stage"], "set": first["set"], "kind": first["kind"],
            "model": first["model"], "conditions": [condition(first), condition(second)], "questions": rows,
            "not_compared": result["not_compared"], "directions": result["directions"]}


def condition(scored: dict) -> dict:
    return {"history": scored.get("history", "fixed"), "order": scored.get("order", "set")}


def differing(conditions: list[dict]) -> str:
    """`history none against fixed` (the second stage's condition against the first's), naming what differs."""
    first, second = conditions
    parts = [f"{key} {second[key]} against {first[key]}" for key in ("history", "order") if first[key] != second[key]]
    return ", ".join(parts)


def conditions_report(result: dict, notes: list[str]) -> str:
    lines = [f"== {result['second']} against {result['first']}: {differing(result['conditions'])}; same code, "
             f"{result['kind']}, {result['set']} set, model {result['model']}"]
    lines += [f"warning: {note}" for note in notes]
    lines += rows_text(result["questions"], "first", "second")
    if result["not_compared"]:
        lines.append(f"  not in both stages, not compared: {', '.join(result['not_compared'])}")
    lines.append(f"  directions: {directions_text(result['directions'])}")
    return "\n".join(lines)


def mid_p_text(p: float) -> str:
    return "< 0.001" if p < 0.0005 else f"{p:.3f}"


def row_text(row: dict) -> str:
    """`more  +0.70 [+0.27, +0.87]  mid-p 0.001`, or what stands in for an interval."""
    if row["direction"] is None:
        return "no samples in one stage: no figures"
    if row["all_same"]:
        estimate = f"{row['all_same']} every sample in both"
    else:
        lo, hi = row["interval"]
        estimate = f"{row['difference']:+.2f} [{lo:+.2f}, {hi:+.2f}]"
    mid_p = row["mid_p_fewer"] if row["direction"] == "fewer" else row["mid_p_more"]
    return f"{row['direction']:<5}  {estimate}  mid-p {mid_p_text(mid_p)}"


def rows_text(rows: dict, first: str, second: str) -> list[str]:
    width = max((len(qid) for qid in rows), default=4)
    counts = {qid: f"{row[first][0]}/{row[first][1]} -> {row[second][0]}/{row[second][1]}" for qid, row in rows.items()}
    span = max((len(c) for c in counts.values()), default=0)
    return [f"  {qid:<{width}}  {counts[qid]:<{span}}  {row_text(row)}" for qid, row in rows.items()]


def directions_text(counts: dict[str, int]) -> str:
    return ", ".join(f"{n} {word}" for word, n in counts.items())


def warnings(first_info: dict, second_info: dict, same_code_expected: bool = False) -> list[str]:
    out = []
    if (not same_code_expected and first_info.get("code_sha256")
            and first_info.get("code_sha256") == second_info.get("code_sha256")):
        out.append("both stages ran the same code (equal code hashes): any difference is noise")
    if first_info.get("ollama_version") != second_info.get("ollama_version"):
        out.append(f"the stages ran on different Ollama versions ({first_info.get('ollama_version')} and "
                   f"{second_info.get('ollama_version')}), whose sampling may differ")
    names = ("first", "second") if same_code_expected else ("current", "candidate")
    for info, which in zip((first_info, second_info), names, strict=True):
        if info.get("kind") in ("rollout", "first-step") and not info.get("finished"):
            out.append(f"the {which} stage is unfinished: its counts are the samples recorded so far")
    if first_info.get("samples") != second_info.get("samples"):
        out.append(f"the stages have different sample counts ({first_info.get('samples')} and "
                   f"{second_info.get('samples')})")
    return out


def report(result: dict, notes: list[str]) -> str:
    lines = [f"== {result['current']} (current) against {result['candidate']} (candidate): {result['kind']}, "
             f"{result['set']} set, model {result['model']}, history {result['history']}, order {result['order']}"]
    lines += [f"warning: {note}" for note in notes]
    lines += rows_text(result["questions"], "current", "candidate")
    if result["not_compared"]:
        lines.append(f"  not in both stages, not compared: {', '.join(result['not_compared'])}")
    lines.append(f"  directions: {directions_text(result['directions'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("current", type=Path, help="the current code's stage (with --conditions: the first stage)")
    parser.add_argument("candidate", type=Path,
                        help="the candidate's stage (with --conditions: the second stage, whose condition differs)")
    parser.add_argument("--conditions", action="store_true",
                        help="compare two conditions (history or order) of one code version: the same figures per "
                             "question")
    parser.add_argument("--db", help=f"the demo database (default {common.default_db_url()})")
    parser.add_argument("--json", action="store_true", help="print the comparison as JSON")
    args = parser.parse_args(argv)
    first, second = score.load_stage(args.current, db=args.db), score.load_stage(args.candidate, db=args.db)
    if args.conditions:
        refused = conditions_refusal(first["info"], second["info"])
        if refused:
            common.fail(refused)
        result = compare_conditions(score.score_stage(first), score.score_stage(second))
        notes = warnings(first["info"], second["info"], same_code_expected=True)
        if args.json:
            print(json.dumps({**result, "warnings": notes}, indent=1))
        else:
            print(conditions_report(result, notes))
        return 0
    refused = refusal(first["info"], second["info"])
    if refused:
        common.fail(refused)
    result = compare(score.score_stage(first), score.score_stage(second))
    notes = warnings(first["info"], second["info"])
    if args.json:
        print(json.dumps({**result, "warnings": notes}, indent=1))
    else:
        print(report(result, notes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
