"""Show one question's samples in a stage of the MCP measurement (docs/mcp-eval.md): each sample's tool calls with the
start of each result, and the start of the answer; with --thinking, the model's thinking for each request too.

    venv/bin/python scripts/mcp_eval/detail.py data/mcp-eval/stages/STAGE dev-2 [--sample 3] [--thinking]

Held-out questions stay unread: this refuses one and shows nothing of it, unless given --reveal, which shows it and
moves the question from questions/holdout.json to questions/dev.json (keeping its id, so git shows the move), since a
question whose transcript was read can be tuned on. Nothing moves from dev to held-out.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
import score  # noqa: E402


def find(question_id: str, folder: Path) -> tuple[str, dict]:
    """(the set holding the question, the question)."""
    for name in common.SETS:
        for question in common.load_set(name, folder / f"{name}.json")["questions"]:
            if question["id"] == question_id:
                return name, question
    common.fail(f"no question {question_id!r} in {', '.join(f'{name}.json' for name in common.SETS)}")


def move_to_dev(question_id: str, folder: Path) -> None:
    """Move a held-out question to the end of the dev set, keeping its id and fields."""
    holdout_path, dev_path = folder / "holdout.json", folder / "dev.json"
    holdout = json.loads(holdout_path.read_text(encoding="utf-8"))
    dev = json.loads(dev_path.read_text(encoding="utf-8"))
    [question] = [q for q in holdout["questions"] if q["id"] == question_id]
    holdout["questions"] = [q for q in holdout["questions"] if q["id"] != question_id]
    dev["questions"].append(question)
    dev_path.write_text(common.dump_set(dev), encoding="utf-8")
    holdout_path.write_text(common.dump_set(holdout), encoding="utf-8")


def samples(folder: Path, question: dict) -> list[tuple[str, list[tuple[dict, dict]]]]:
    """(label, the question's exchanges) for each sample of the stage."""
    info = common.read_stage(folder) or {"kind": "session"}
    out = []
    if info["kind"] == "session":
        for capture in sorted(folder.glob("run*/capture.jsonl"), key=lambda p: int(p.parent.name[3:])):
            out.append((capture.parent.name, score.session_exchanges(capture)))
    else:
        path = folder / "samples.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
            sample = json.loads(line)
            if sample["question"] == question["id"]:
                exchanges = [(e["request"], e["reply"]) for e in sample["exchanges"]]
                out.append((f"sample{sample['sample']}", exchanges))
    return out


def show(label: str, exchanges: list[tuple[dict, dict]], question: dict, thinking: bool, tools) -> list[str]:
    record = score.records(exchanges, [question], tools=tools).get(question["id"])
    lines = [f"## {label} {question['id']}"]
    if record is None:
        return lines + ["   not reached"]
    results = record["results"] + [""] * max(0, len(record["calls"]) - len(record["results"]))
    for call, result in zip(record["calls"], results, strict=False):
        lines.append(f"   CALL {call['tool']} {json.dumps(call['arguments'], ensure_ascii=False)} -> "
                     + result[:200].replace("\n", " "))
    state = "ANSWER" if record["answered"] else "UNANSWERED (loop limit)"
    lines.append(f"   {state}: " + record["answer"][:900].replace("\n", " | "))
    if thinking:
        for i, (request, reply) in enumerate(exchanges):
            users = [m for m in request.get("messages") or [] if m.get("role") == "user"]
            if users and users[-1].get("content") == question["text"]:
                lines.append(f"   THINKING (request {i + 1}): " + (reply.get("thinking") or "")[:3000])
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("stage", type=Path, help="the stage folder")
    parser.add_argument("question", help="the question id, such as dev-2")
    parser.add_argument("--sample", type=int, help="only this sample (rollouts) or run (sessions) number")
    parser.add_argument("--thinking", action="store_true", help="also print the model's thinking")
    parser.add_argument("--reveal", action="store_true",
                        help="show a held-out question, moving it to the dev set for good")
    parser.add_argument("--questions-dir", type=Path, default=common.QUESTIONS, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    set_name, question = find(args.question, args.questions_dir)
    if set_name == "holdout":
        if not args.reveal:
            common.fail(f"{args.question} is a held-out question, so its transcripts stay unread. --reveal shows it "
                        "and moves it to the dev set for good (docs/mcp-eval.md, \"Held-out questions\")")
        move_to_dev(args.question, args.questions_dir)
        print(f"moved {args.question} from holdout.json to dev.json: it is a dev question from now on, and held-out "
              "stages run before the move no longer compare with later ones", file=sys.stderr)
    info = common.read_stage(args.stage) or {}
    found = samples(args.stage, question)
    if args.sample is not None:
        found = [(label, ex) for label, ex in found if label.removeprefix("run").removeprefix("sample")
                 == str(args.sample)]
    if not found:
        print(f"no samples of {args.question} in {args.stage}", file=sys.stderr)
        return 1
    for label, exchanges in found:
        print("\n".join(show(f"{args.stage.name}/{label}", exchanges, question, args.thinking, info.get("tools"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
