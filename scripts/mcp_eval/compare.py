"""Compare two stages of the MCP measurement (docs/mcp-eval.md): per question, the pass counts of both and a verdict,
and the set's verdict.

    venv/bin/python scripts/mcp_eval/compare.py data/mcp-eval/stages/CURRENT data/mcp-eval/stages/CANDIDATE [--json]
    venv/bin/python scripts/mcp_eval/compare.py --conditions data/mcp-eval/stages/A data/mcp-eval/stages/B [--json]

The first stage is the current code, the second the candidate. For each question, a one-sided exact test (Fisher's,
from the hypergeometric distribution) of the two pass counts gives p for "the candidate passes more often" and for
"less often": `better` or `worse` at p <= 0.05, `within noise` otherwise. The set is `better` when some question is
`better` and none `worse`, `worse` when any question is `worse`, `within noise` otherwise. No correction is made for
testing several questions; the adoption rule (docs/mcp-eval.md, the `mcp-evaluation` spec) compares under both the
`fixed` and the `none` history conditions, and asks the held-out set and a session batch to agree.

Stages of different sets, models, kinds, history conditions or orders are refused (exit 2). Equal code hashes and
different Ollama versions are warned about. Held-out questions are shown as counts only, as everywhere.

`--conditions A B` compares two stages of the same code (equal code hashes), set, model and kind that differ in
history condition or order: the same tests per question, named for what they measure, `more` (B passes more often),
`fewer` or `within noise`, with both p-values. It attributes a difference to the history (or order); it gives no set
verdict and decides nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
import score  # noqa: E402

ALPHA = 0.05


def p_more(a: int, n: int, b: int, m: int) -> float:
    """One-sided Fisher exact test: the probability, with the a + b passes of n + m samples shared at random, that
    the second stage's m samples hold b passes or more."""
    passes, total = a + b, n + m
    hi = min(passes, m)
    return sum(comb(passes, x) * comb(total - passes, m - x) for x in range(b, hi + 1)) / comb(total, m)


def p_less(a: int, n: int, b: int, m: int) -> float:
    """The same for b passes or fewer."""
    passes, total = a + b, n + m
    lo = max(0, m - (total - passes))
    return sum(comb(passes, x) * comb(total - passes, m - x) for x in range(lo, b + 1)) / comb(total, m)


def verdict(a: int, n: int, b: int, m: int) -> tuple[str, float, float]:
    more, less = p_more(a, n, b, m), p_less(a, n, b, m)
    if n and m and more <= ALPHA:
        return "better", more, less
    if n and m and less <= ALPHA:
        return "worse", more, less
    return "within noise", more, less


def set_verdict(verdicts: list[str]) -> str:
    if "worse" in verdicts:
        return "worse"
    if "better" in verdicts:
        return "better"
    return "within noise"


def compare(first: dict, second: dict) -> dict:
    """Two scored stages (score.score_stage) and their stage.json descriptions, compared."""
    questions = [qid for qid in first["questions"] if qid in second["questions"]]
    rows = {}
    for qid in questions:
        a, n = first["questions"][qid]["passed"], first["questions"][qid]["samples"]
        b, m = second["questions"][qid]["passed"], second["questions"][qid]["samples"]
        word, more, less = verdict(a, n, b, m)
        rows[qid] = {"current": [a, n], "candidate": [b, m], "verdict": word, "p_better": more, "p_worse": less}
    only = sorted(set(first["questions"]) ^ set(second["questions"]))
    return {"current": first["stage"], "candidate": second["stage"], "set": first["set"], "kind": first["kind"],
            "model": first["model"], "history": condition(first)["history"], "order": condition(first)["order"],
            "questions": rows, "not_compared": only,
            "verdict": set_verdict([row["verdict"] for row in rows.values()])}


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


CONDITION_WORDS = {"better": "more", "worse": "fewer", "within noise": "within noise"}


def compare_conditions(first: dict, second: dict) -> dict:
    """Two scored stages of one code version under different conditions: per question both pass counts, both
    p-values and `more` (the second passes more often), `fewer` or `within noise`; no set verdict."""
    result = compare(first, second)
    rows = {qid: {"first": row["current"], "second": row["candidate"], "verdict": CONDITION_WORDS[row["verdict"]],
                  "p_more": row["p_better"], "p_fewer": row["p_worse"]}
            for qid, row in result["questions"].items()}
    return {"first": first["stage"], "second": second["stage"], "set": first["set"], "kind": first["kind"],
            "model": first["model"], "conditions": [condition(first), condition(second)], "questions": rows,
            "not_compared": result["not_compared"]}


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
    width = max((len(qid) for qid in result["questions"]), default=4)
    for qid, row in result["questions"].items():
        (a, n), (b, m) = row["first"], row["second"]
        lines.append(f"  {qid:<{width}}  {a}/{n} -> {b}/{m}  {row['verdict']:<12}  p(more) {row['p_more']:.4f}  "
                     f"p(fewer) {row['p_fewer']:.4f}")
    if result["not_compared"]:
        lines.append(f"  not in both stages, not compared: {', '.join(result['not_compared'])}")
    lines.append("  (an attribution: no set verdict)")
    return "\n".join(lines)


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
    width = max((len(qid) for qid in result["questions"]), default=4)
    for qid, row in result["questions"].items():
        (a, n), (b, m) = row["current"], row["candidate"]
        lines.append(f"  {qid:<{width}}  {a}/{n} -> {b}/{m}  {row['verdict']:<12}  p(better) {row['p_better']:.4f}  "
                     f"p(worse) {row['p_worse']:.4f}")
    if result["not_compared"]:
        lines.append(f"  not in both stages, not compared: {', '.join(result['not_compared'])}")
    lines.append(f"  set: {result['verdict']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("current", type=Path, help="the current code's stage (with --conditions: the first stage)")
    parser.add_argument("candidate", type=Path,
                        help="the candidate's stage (with --conditions: the second stage, whose condition differs)")
    parser.add_argument("--conditions", action="store_true",
                        help="compare two conditions (history or order) of one code version: more, fewer or "
                             "within noise per question, no set verdict")
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
