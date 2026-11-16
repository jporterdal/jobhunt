"""Score stages of the MCP measurement (docs/mcp-eval.md): per question, how many samples passed each check and in how
many samples each diagnostic was seen, and per set, how many samples passed every question.

    venv/bin/python scripts/mcp_eval/score.py data/mcp-eval/stages/STAGE [STAGE ...] [--json]

A stage is a folder of `rollout.py` (samples.jsonl) or `batch.py` (run<k>/capture.jsonl), described by its
stage.json. A folder of session runs without one (such as add-mcp-server's `data/mcp-smoke/runs/<stage>/`) is read
as a session stage of the set given by `--set` (dev by default).

Which checks a stage scores: a full stage (sessions, rollouts) every check but `first_call`; a single-step stage
(`rollout.py --first-step`) only the `first_call` checks, since it has no answer. A sample passes a question when
every check scored passes; a question without a scored check isn't reported. Held-out questions are reported as
counts only, like every other question here: this command never prints calls, results or answers (`detail.py` does,
for dev questions).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402

ANSWER_CHECKS = ("answer_urls", "answer_figures", "answer_mentions", "answer_amounts")
DIAGNOSTICS = (
    "url_as_job_id",   # an integer above 10^9 passed as a job_id: the number in a posting's URL
    "combined_q",      # a search `q` holding a demo company's name and other words (title and company in one q)
    "invented_args",   # an argument name the tool's schema doesn't have
    "unknown_tool",    # a call to a name the client doesn't offer
    "carried_filter",  # a search with a filter the question doesn't ask for (its unasked_filters)
    "made_up_amount",  # a money amount in the answer that no tool result of that sample holds
    "refused",         # a call answered with an error (refused, or a posting not found)
    "warnings",        # a result that begins with warnings (arguments left out)
    "unanswered",      # stopped at the client's loop limit without an answer
)
ANSWER_DIAGNOSTICS = ("made_up_amount", "unanswered")
JOB_ID_FROM_URL = 10**9

# --- reading answers ---

_URL_NUMBER = re.compile(r"/view/(\d{6,})")
_NUMBER = re.compile(r"(\d+(?:\.\d+)?)\s*(%?)")
_DOLLARS = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s?([kK]\b)?")
_GROUPED = re.compile(r"(?<![\d.,$])(\d{1,3}(?:,\d{3})+)(?![\d,]*\d)")
_THOUSANDS = re.compile(r"(?<![\d.,$])(\d{2,3})\s?[kK]\b")
_INTEGER = re.compile(r"\d{1,3}(?:,\d{3})+|\d+")


def url_numbers(text: str) -> set[str]:
    """The numbers in the posting URLs a text holds (`.../view/<number>`)."""
    return set(_URL_NUMBER.findall(text or ""))


def has_figure(text: str, figure: float) -> bool:
    """Whether `text` reports `figure` up to rounding: a number in it, as a decimal or a percent, within 0.01."""
    for value, pct in _NUMBER.findall(text or ""):
        if abs(float(value) / (100 if pct else 1) - figure) < 0.01:
            return True
    return False


def money_amounts(text: str) -> set[int]:
    """The money amounts of 1,000 or more in a text: `$105,000`, `$105000`, `$105k`, `105,000` and `125k`."""
    found = set()
    for digits, k in _DOLLARS.findall(text or ""):
        found.add(int(digits.replace(",", "")) * (1000 if k else 1))
    for digits in _GROUPED.findall(text or ""):
        found.add(int(digits.replace(",", "")))
    for digits in _THOUSANDS.findall(text or ""):
        found.add(int(digits) * 1000)
    return {amount for amount in found if amount >= 1000}


def result_numbers(texts: list[str]) -> set[int]:
    """Every whole number in the tool results (digits, or grouped with commas), with their money amounts."""
    numbers: set[int] = set()
    for text in texts:
        numbers |= {int(n.replace(",", "")) for n in _INTEGER.findall(text)}
        numbers |= money_amounts(text)
    return numbers


def _norm(text: str) -> str:
    return (text or "").replace("’", "'").replace("‘", "'").casefold()


def mentions(text: str, name: str) -> bool:
    return _norm(name) in _norm(text)


def _same(expected, given) -> bool:
    if isinstance(expected, str) and isinstance(given, str):
        return expected.casefold() == given.casefold()
    return expected == given


def has_arguments(arguments: dict, expected: dict) -> bool:
    """Whether `arguments` hold every expected argument with its value (text compared ignoring case)."""
    return all(key in arguments and _same(value, arguments[key]) for key, value in expected.items())


# --- records ---


def tool_schemas(tools: list[dict]) -> dict[str, set[str]]:
    """{tool name without the prefix: its argument names}, from the tools a request carried."""
    prefix = common.wire_name("")
    return {
        tool["function"]["name"].removeprefix(prefix): set((tool["function"].get("parameters") or {}).get("properties")
                                                           or {})
        for tool in tools
    }


def _call(call: dict) -> dict:
    name = call["function"]["name"]
    try:
        arguments = common.call_arguments(call)
    except ValueError:
        arguments = {}
    return {"name": name, "tool": name.removeprefix(common.wire_name("")), "arguments": arguments}


def records(exchanges: list[tuple[dict, dict]], questions: list[dict], tools: list[dict] | None = None) -> dict:
    """Per-question records from a sequence of (request, assembled reply), as a session capture or a rollout holds
    them: {question id: {calls, first_calls, results, answer, answered, tokens, schemas}}. A request belongs to the
    question whose text is its last user message; requests of other questions are skipped."""
    by_text = {question["text"]: question["id"] for question in questions}
    out: dict[str, dict] = {}
    for request, reply in exchanges:
        messages = request.get("messages") or []
        users = [i for i, message in enumerate(messages) if message.get("role") == "user"]
        if not users:
            continue
        qid = by_text.get(messages[users[-1]].get("content"))
        if qid is None:
            continue
        record = out.setdefault(qid, {"calls": [], "first_calls": None, "results": [], "answer": "", "answered": False,
                                      "tokens": 0, "replies": 0,
                                      "schemas": tool_schemas(request.get("tools") or tools or [])})
        after = messages[users[-1] + 1:]
        results = [message.get("content") or "" for message in after if message.get("role") == "tool"]
        if len(results) > len(record["results"]):
            record["results"] = results
        calls = [_call(call) for call in reply.get("tool_calls") or []]
        if record["first_calls"] is None:
            record["first_calls"] = calls
        record["calls"] += calls
        record["replies"] += 1
        record["tokens"] = max(record["tokens"], reply.get("prompt_eval_count") or 0)
        if reply.get("content"):
            record["answer"] = reply["content"]  # the client keeps the last reply with text as the answer
        if not calls:
            record["answered"] = True
    for record in out.values():
        if not record["answered"]:
            record["answer"] = ""
    return out


def session_exchanges(capture: Path) -> list[tuple[dict, dict]]:
    """The /api/chat exchanges of a capture proxy's file, in order."""
    exchanges = []
    for line in capture.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("path") == "/api/chat" and isinstance(record.get("response"), dict):
            assembled = record["response"].get("assembled")
            if isinstance(assembled, dict) and isinstance(record.get("request"), dict):
                exchanges.append((record["request"], assembled))
    return exchanges


# --- checks and diagnostics ---


def check_passes(check: dict, record: dict) -> bool:
    kind, answer = check["kind"], record["answer"]
    if kind == "answer_urls":
        found = url_numbers(answer)
        return found == set(check["exact"]) if "exact" in check else set(check["includes"]) <= found
    if kind == "answer_figures":
        return all(has_figure(answer, value) for value in check["values"])
    if kind == "answer_mentions":
        return all(mentions(answer, name) for name in check["names"])
    if kind == "answer_amounts":
        return money_amounts(answer) == set(check["amounts"])
    if kind == "called":
        return any(call["tool"] == check["tool"] and has_arguments(call["arguments"], check.get("arguments") or {})
                   for call in record["calls"])
    if kind == "first_call":
        calls = record["first_calls"] or []
        if not calls:
            return False
        first = calls[0]
        return (first["tool"] == check["tool"]
                and has_arguments(first["arguments"], check.get("arguments") or {})
                and all(name in first["arguments"] for name in check.get("with") or [])
                and not any(name in first["arguments"] for name in check.get("without") or []))
    raise ValueError(f"unknown check {kind!r}")


def scored_checks(question: dict, kind: str) -> list[dict]:
    """The checks a stage of `kind` scores for a question: `first_call` only in a single-step stage, every other
    check otherwise."""
    if kind == "first-step":
        return [check for check in question["checks"] if check["kind"] == "first_call"]
    return [check for check in question["checks"] if check["kind"] != "first_call"]


def check_label(check: dict) -> str:
    return f"{check['kind']}:{check['tool']}" if check["kind"] in ("called", "first_call") else check["kind"]


def diagnostics(record: dict, question: dict, companies: list[str], kind: str) -> dict[str, int]:
    """Each diagnostic's count in one sample."""
    calls = record["calls"]
    searches = [call["arguments"] for call in calls if call["tool"] == "search_postings"]
    out = dict.fromkeys(DIAGNOSTICS, 0)
    out["url_as_job_id"] = sum(1 for call in calls if isinstance(call["arguments"].get("job_id"), int)
                               and not isinstance(call["arguments"]["job_id"], bool)
                               and call["arguments"]["job_id"] > JOB_ID_FROM_URL)
    for arguments in searches:
        q = str(arguments.get("q") or "")
        for company in companies:
            if company.casefold() in q.casefold():
                rest = re.sub(re.escape(company), " ", q, flags=re.IGNORECASE)
                if re.search(r"\w", rest):
                    out["combined_q"] += 1
                    break
    for call in calls:
        schema = record["schemas"].get(call["tool"])
        if schema is None or not call["name"].startswith(common.wire_name("")):
            out["unknown_tool"] += 1
        else:
            out["invented_args"] += sum(1 for name in call["arguments"] if name not in schema)
    unasked = set(question.get("unasked_filters") or [])
    out["carried_filter"] = sum(1 for arguments in searches if unasked & set(arguments))
    errors = ("Error executing tool", "Error calling tool")
    out["refused"] = sum(1 for text in record["results"] if text.startswith(errors))
    out["warnings"] = sum(1 for text in record["results"] if text.lstrip().startswith('{\n  "warnings"')
                          or text.lstrip().startswith('{"warnings"'))
    if kind != "first-step":
        out["made_up_amount"] = len(money_amounts(record["answer"]) - result_numbers(record["results"]))
        out["unanswered"] = int(not record["answered"])
    return out


def score_sample(record: dict | None, question: dict, companies: list[str], kind: str) -> dict:
    """One sample of one question: each scored check, whether all passed, the diagnostics, calls and prompt size.
    A question the sample never reached (no record) fails every check."""
    record = record or {"calls": [], "first_calls": [], "results": [], "answer": "", "answered": False, "tokens": 0,
                        "replies": 0, "schemas": {}}
    checks = scored_checks(question, kind)
    passed = [check_passes(check, record) for check in checks]
    return {
        "checks": passed, "passed": bool(checks) and all(passed),
        "diagnostics": diagnostics(record, question, companies, kind),
        "tool_calls": len(record["calls"]), "tokens": record["tokens"], "reached": record["replies"] > 0,
    }


# --- stages ---


def load_stage(folder: Path, set_name: str | None = None, db: str | None = None) -> dict:
    """A stage's description and its samples: {info, questions, samples: {question id: [record or None, ...]}}.
    Session runs are samples by run number (a question a run never reached is None); rollouts by sample number."""
    folder = Path(folder)
    info = common.read_stage(folder)
    if info is None:
        if not any(folder.glob("run*/capture.jsonl")):
            common.fail(f"{folder} is not a stage (no stage.json and no run*/capture.jsonl)")
        info = {"kind": "session", "set": set_name or "dev", "model": None, "legacy": True}
    if set_name and set_name != info["set"]:
        common.fail(f"{folder} is a stage of the {info['set']} set, not {set_name}")
    qset = common.load_set(info["set"])
    questions = qset["questions"]
    if info.get("questions"):
        ids = {question["id"] for question in questions}
        missing = [qid for qid in info["questions"] if qid not in ids]
        if missing:
            print(f"note: {folder.name}: {', '.join(missing)} no longer in the {info['set']} set; not scored",
                  file=sys.stderr)
        questions = [question for question in questions if question["id"] in info["questions"]]
    samples: dict[str, list] = {question["id"]: [] for question in questions}
    if info["kind"] == "session":
        runs = sorted(folder.glob("run*/capture.jsonl"), key=lambda p: int(p.parent.name[3:]))
        for capture in runs:
            exchanges = session_exchanges(capture)
            if exchanges and not info.get("model"):
                info["model"] = exchanges[0][0].get("model")
            got = records(exchanges, questions)
            for question in questions:
                samples[question["id"]].append(got.get(question["id"]))
    else:
        path = folder / "samples.jsonl"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        if text and not text.endswith("\n"):  # a sample being written, or cut off by a kill
            text = text[:text.rfind("\n") + 1]
        for line in text.splitlines():
            sample = json.loads(line)
            if sample["question"] not in samples:
                continue
            exchanges = [(exchange["request"], exchange["reply"]) for exchange in sample["exchanges"]]
            got = records(exchanges, questions, tools=info.get("tools"))
            samples[sample["question"]].append(got.get(sample["question"]))
    companies = info.get("companies")
    if companies is None:
        url = db or common.default_db_url()
        common.ensure_demo(url)
        engine = common.open_demo(url)
        companies = common.demo_companies(engine)
        engine.dispose()
    return {"folder": folder, "info": info, "questions": questions, "samples": samples, "companies": companies}


def score_stage(stage: dict) -> dict:
    """Per question: samples, passes, each check's passes and each diagnostic's sample count; and the set's."""
    kind = stage["info"]["kind"]
    out = {"stage": stage["folder"].name, "kind": kind, "set": stage["info"]["set"],
           "model": stage["info"].get("model"), "questions": {}}
    per_sample: dict[int, list[bool]] = {}
    for question in stage["questions"]:
        checks = scored_checks(question, kind)
        if not checks:
            continue
        scored = [score_sample(record, question, stage["companies"], kind)
                  for record in stage["samples"][question["id"]]]
        for k, sample in enumerate(scored):
            per_sample.setdefault(k, []).append(sample["passed"])
        out["questions"][question["id"]] = {
            "samples": len(scored),
            "passed": sum(sample["passed"] for sample in scored),
            "checks": {check_label(check): sum(sample["checks"][i] for sample in scored)
                       for i, check in enumerate(checks)},
            "diagnostics": {name: sum(1 for sample in scored if sample["diagnostics"][name])
                            for name in DIAGNOSTICS
                            if kind != "first-step" or name not in ANSWER_DIAGNOSTICS},
            "tool_calls": round(sum(sample["tool_calls"] for sample in scored) / len(scored), 1) if scored else 0,
            "max_tokens": max((sample["tokens"] for sample in scored), default=0),
            "not_reached": sum(1 for sample in scored if not sample["reached"]),
        }
    counted = [passes for passes in per_sample.values() if len(passes) == len(out["questions"])]
    out["all_passed"] = sum(all(passes) for passes in counted)
    out["all_samples"] = len(counted)
    return out


def report(scored: dict, info: dict) -> str:
    kind = scored["kind"]
    scope = "first_call checks only" if kind == "first-step" else "answer and call checks (not first_call)"
    lines = [f"== {scored['stage']}: {kind}, {scored['set']} set, model {scored['model'] or 'unknown'}; "
             f"checks scored: {scope}"]
    if info.get("legacy"):
        lines.append("   (session runs without stage.json)")
    if kind in ("rollout", "first-step") and not info.get("finished"):
        lines.append(f"   unfinished ({info.get('stopped') or 'running, or stopped without a record'}); continue "
                     f"it with rollout.py {scored['stage']} --resume")
    width = max((len(qid) for qid in scored["questions"]), default=4)
    for qid, q in scored["questions"].items():
        checks = " ".join(f"{label} {count}/{q['samples']}" for label, count in q["checks"].items())
        seen = " ".join(f"{name} {count}" for name, count in q["diagnostics"].items() if count)
        extra = f"; not reached {q['not_reached']}" if q["not_reached"] else ""
        lines.append(f"  {qid:<{width}}  passed {q['passed']}/{q['samples']}  [{checks}]")
        lines.append(f"  {'':<{width}}  samples with: {seen or 'none'}; tool calls {q['tool_calls']} a sample, "
                     f"largest prompt {q['max_tokens']} tokens{extra}")
    if scored["questions"]:
        how = "runs" if kind == "session" else "samples (paired by sample number)"
        lines.append(f"  every question passed: {scored['all_passed']}/{scored['all_samples']} {how}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("stages", nargs="+", type=Path, help="stage folders (data/mcp-eval/stages/<stage>)")
    parser.add_argument("--set", choices=common.SETS, help="the set of a session folder without stage.json (dev)")
    parser.add_argument("--db", help="the demo database, for the company names of a stage without them "
                                     f"(default {common.default_db_url()})")
    parser.add_argument("--json", action="store_true", help="print the figures as JSON")
    args = parser.parse_args(argv)
    results = []
    for folder in args.stages:
        stage = load_stage(folder, args.set, args.db)
        scored = score_stage(stage)
        results.append(scored)
        if not args.json:
            print(report(scored, stage["info"]))
    if args.json:
        print(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
