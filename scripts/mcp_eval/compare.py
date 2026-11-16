"""Compare two stages of the MCP measurement (docs/mcp-eval.md): per question, the pass counts of both and a verdict,
and the set's verdict.

    venv/bin/python scripts/mcp_eval/compare.py data/mcp-eval/stages/CURRENT data/mcp-eval/stages/CANDIDATE [--json]

The first stage is the current code, the second the candidate. For each question, a one-sided exact test (Fisher's,
from the hypergeometric distribution) of the two pass counts gives p for "the candidate passes more often" and for
"less often": `better` or `worse` at p <= 0.05, `within noise` otherwise. The set is `better` when some question is
`better` and none `worse`, `worse` when any question is `worse`, `within noise` otherwise. No correction is made for
testing several questions; the adoption rule (docs/mcp-eval.md) asks the held-out set and a session batch to agree.

Stages of different sets, models or kinds are refused (exit 2). Equal code hashes and different Ollama versions are
warned about. Held-out questions are shown as counts only, as everywhere.
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
            "model": first["model"], "questions": rows, "not_compared": only,
            "verdict": set_verdict([row["verdict"] for row in rows.values()])}


def refusal(first_info: dict, second_info: dict) -> str | None:
    for key, what in (("set", "sets"), ("kind", "kinds"), ("model", "models")):
        if first_info.get(key) != second_info.get(key):
            return (f"the stages are of different {what} ({first_info.get(key)} and {second_info.get(key)}); "
                    "only stages of one set, kind and model are compared")
    return None


def warnings(first_info: dict, second_info: dict) -> list[str]:
    out = []
    if first_info.get("code_sha256") and first_info.get("code_sha256") == second_info.get("code_sha256"):
        out.append("both stages ran the same code (equal code hashes): any difference is noise")
    if first_info.get("ollama_version") != second_info.get("ollama_version"):
        out.append(f"the stages ran on different Ollama versions ({first_info.get('ollama_version')} and "
                   f"{second_info.get('ollama_version')}), whose sampling may differ")
    for info, which in ((first_info, "current"), (second_info, "candidate")):
        if info.get("kind") in ("rollout", "first-step") and not info.get("finished"):
            out.append(f"the {which} stage is unfinished: its counts are the samples recorded so far")
    if first_info.get("samples") != second_info.get("samples"):
        out.append(f"the stages have different sample counts ({first_info.get('samples')} and "
                   f"{second_info.get('samples')})")
    return out


def report(result: dict, notes: list[str]) -> str:
    lines = [f"== {result['current']} (current) against {result['candidate']} (candidate): {result['kind']}, "
             f"{result['set']} set, model {result['model']}"]
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
    parser.add_argument("current", type=Path, help="the current code's stage")
    parser.add_argument("candidate", type=Path, help="the candidate's stage")
    parser.add_argument("--db", help=f"the demo database (default {common.default_db_url()})")
    parser.add_argument("--json", action="store_true", help="print the comparison as JSON")
    args = parser.parse_args(argv)
    first, second = score.load_stage(args.current, db=args.db), score.load_stage(args.candidate, db=args.db)
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
