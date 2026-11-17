"""Rollouts of the MCP measurement (docs/mcp-eval.md): each question answered the way the documented client (ollmcp
0.35.1) would answer it, without the client, sampled many times under one history condition.

    venv/bin/python scripts/mcp_eval/rollout.py STAGE [--set dev] [--questions dev-2,dev-3] [--samples 10]
        [--first-step] [--history fixed|own|none] [--order set|balanced] [--model qwen3:8b]
        [--ollama-url http://127.0.0.1:11434] [--db URL] [--dry-run]
    venv/bin/python scripts/mcp_eval/rollout.py STAGE --resume [--ollama-url URL] [--db URL] [--dry-run]
    venv/bin/python scripts/mcp_eval/rollout.py --check CAPTURE [--db URL]

A rollout of a question sends Ollama the requests the client sends: the tools listed by the working tree's server and
rendered as the client renders them, the client's options, the question's history, then the question; each tool call
is answered by calling the working tree's server in-process (through the SDK's in-memory client, so arguments are
sifted as in a session) and passed on as the client passes it; it stops at an answer or after the client's 7 loops
(unanswered). Only `stream` differs from the client (false: the same sampling, one reply to record). `--first-step`
sends only each question's first request and records its tool calls.

The history (`--history`, the `mcp-evaluation` spec's "History conditions"): `fixed` (the default) is the earlier
questions of the set with their written `history_answer`s; `none` is no earlier message at all; `own` runs chains,
each asking the whole set in order and keeping the answers the model gave as history for the later questions (a
question stopped at the loop limit left out), so chain k gives sample k of every question. The order (`--order`) is
the set's by default; `balanced` uses the rows of a Williams design over the set (`common.williams`), sample k taking
row ((k - 1) mod rows) + 1, for one-off evaluations.

Every request, reply and tool result goes to data/mcp-eval/stages/STAGE/samples.jsonl, and what ran to stage.json
(with copies of mcp_server.py and mcp_tools.py). Each sample is written as it finishes, so a stage stopped (Ctrl-C, a
failed request, a reboot) keeps what it recorded; `--resume` runs the samples it lacks, with the stage's own options
(history and order among them; an `own` chain continues at its first unrecorded question with its recorded answers),
and is refused when the code, the set's questions, the tools or the Ollama version changed.

`--check CAPTURE` replays a real session's capture (from `batch.py`, or `scripts/ollama_capture.py` around the
client): each captured request is built again from the capture's own questions, answers and tool calls, with tool
results from the working tree's server, and compared in its tools, options and messages. Run it whenever the
documented client's version changes, on a fresh session of the same code; exit 1 when a request differs.

Demo database only, loopback Ollama only; each run states what it will send first, and --dry-run stops there.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
import score  # noqa: E402

FULL_SAMPLES = 10
FIRST_STEP_SAMPLES = 30


# --- rollouts ---


def _stored(body: dict) -> dict:
    """A request as recorded: the tools are the stage's (in stage.json), so they aren't repeated."""
    return {**{k: v for k, v in body.items() if k != "tools"}, "tools_from": "stage.json"}


async def rollout(ollama: common.Ollama, server: common.Server, model: str, before: list[dict], question: dict,
                  first_step: bool = False, on_request=None) -> dict:
    """One rollout of `question` after the history messages `before`: {answered (None for a single step), loops,
    exchanges, results}."""
    messages = [*before, {"role": "user", "content": question["text"]}]
    exchanges, results, loops = [], [], 0
    while True:
        body = common.request_body(model, list(messages), server.tools)
        started = time.monotonic()
        reply = common.assembled(ollama.chat(body))
        exchanges.append({"request": _stored(body), "reply": reply, "seconds": round(time.monotonic() - started, 2)})
        if on_request is not None:
            on_request()
        calls = reply["tool_calls"]
        if first_step:
            return {"answered": None, "loops": 0, "exchanges": exchanges, "results": results}
        if not calls:
            return {"answered": True, "loops": loops, "exchanges": exchanges, "results": results}
        if loops >= common.LOOP_LIMIT:
            return {"answered": False, "loops": loops, "exchanges": exchanges, "results": results}
        loops += 1
        messages.append(common.assistant_message(reply))
        for call in calls:
            content = await server.answer(call)
            results.append({"name": call["function"]["name"], "arguments": common.call_arguments(call),
                            "content": content})
            if content is not None:
                messages.append(common.tool_message(call["function"]["name"], content))


HISTORY_WORDS = {
    "fixed": "fixed (each question after the earlier ones with their written history answers)",
    "own": "own (chains: each question after the earlier ones with the answers the model gave them in its chain)",
    "none": "none (each question alone)",
}


def statement(args, questions: list[dict], samples: int, orders: list[list[str]] | None, done: int = 0) -> str:
    kind = "single-step rollouts (each question's first request only)" if args.first_step else "full rollouts"
    most = 1 if args.first_step else common.LOOP_LIMIT + 1
    ids = ", ".join(question["id"] for question in questions)
    total = len(questions) * samples
    unit = "chains" if args.history == "own" else "samples"
    lines = [f"rollout stage {args.stage}: {kind} of the {args.set} set with {args.model}, one code version (the "
             f"working tree, code {common.code_hash()[:12]})",
             f"  {len(questions)} questions ({ids}) x {samples} {unit} = {total} rollouts, "
             f"up to {most} request{'s' if most > 1 else ''} each, to Ollama at {args.ollama_url}",
             f"  history: {HISTORY_WORDS[args.history]}"]
    if orders is None:
        lines.append("  order: the set's")
    else:
        lines.append(f"  order: balanced, {len(orders)} orders (a Williams design); sample k uses order "
                     f"((k - 1) mod {len(orders)}) + 1")
        if samples % len(orders):
            lines.append(f"  note: the stage isn't balanced: {samples} samples a question isn't a multiple of the "
                         f"{len(orders)} orders, so {samples % len(orders)} orders are used once more than the rest")
    if args.resume:
        lines.append(f"  resuming: {done} recorded, {total - done} left to run")
    return "\n".join(lines)


def done_samples(folder: Path) -> dict[tuple[str, int], dict]:
    """The samples a stopped stage already recorded, by (question, sample). A last line cut off by a kill is removed
    from samples.jsonl, so the stage reads cleanly and that sample runs again."""
    path = folder / "samples.jsonl"
    if not path.exists():
        return {}
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        data = data[:data.rfind(b"\n") + 1]
        path.write_bytes(data)
        print("note: removed a sample cut off when the stage stopped; it runs again", file=sys.stderr)
    done = {}
    for line in data.decode("utf-8").splitlines():
        sample = json.loads(line)
        done[(sample["question"], sample["sample"])] = sample
    return done


def final_answer(sample: dict) -> str | None:
    """What the client keeps as a question's answer for the next question's history: the last reply with text, or
    None when the question was stopped at the loop limit (not kept)."""
    if not sample.get("answered"):
        return None
    texts = [exchange["reply"].get("content") for exchange in sample["exchanges"] if exchange["reply"].get("content")]
    return texts[-1] if texts else ""


def resumed_info(folder: Path, args) -> dict:
    """A stopped rollout stage's stage.json, with args filled in from it; refuses (exit 2) anything that would mix
    two runs: another kind, a finished stage, options that differ from the stage's, or changed code or questions."""
    info = common.read_stage(folder)
    if info is None:
        common.fail(f"no stage to resume at {folder}")
    if info.get("kind") not in ("rollout", "first-step"):
        common.fail(f"{folder.name} is a {info.get('kind')} stage; only rollout stages can be resumed")
    if info.get("finished"):
        common.fail(f"{folder.name} already finished")
    given = {"--set": args.set, "--questions": args.questions, "--samples": args.samples, "--model": args.model,
             "--history": args.history, "--order": args.order}
    given = [option for option, value in given.items() if value is not None] + (["--first-step"] * args.first_step)
    if given:
        common.fail(f"--resume takes the stage's own options; leave out {', '.join(given)}")
    args.set, args.model, args.samples = info["set"], info["model"], info["samples"]
    args.questions, args.first_step = ",".join(info["questions"]), info["kind"] == "first-step"
    found = common.conditions(info)
    args.history, args.order = found["history"], found["order"]
    if info.get("code_sha256") != common.code_hash():
        common.fail(f"mcp_server.py or mcp_tools.py changed since {folder.name} started (its copies are in "
                    f"{folder / 'code'}); restore them to resume, or start a new stage")
    return info


def planned(questions: list[dict], selected: list[int], samples: int, history: str,
            orders: list[list[str]] | None) -> list[tuple[int, int, list[str] | None, int | None]]:
    """The rollouts of a stage in the order they run, as (sample, question index, its order or None, its row number
    or None). `fixed` and `none` interleave the questions sample by sample, so a stage stopped early is even across
    questions; `own` runs chain by chain, each chain asking every question in its order."""
    ids = [question["id"] for question in questions]
    out = []
    for k in range(1, samples + 1):
        row = (k - 1) % len(orders) + 1 if orders else None
        order = orders[row - 1] if orders else None
        if history == "own":
            out += [(k, ids.index(qid), order, row) for qid in (order or ids)]
        else:
            out += [(k, i, order, row) for i in selected]
    return out


async def run_stage(args, engine, questions: list[dict], selected: list[int], samples: int, folder: Path,
                    ollama: common.Ollama, orders: list[list[str]] | None = None, prior: dict | None = None,
                    done: dict | None = None) -> int:
    kind = "first-step" if args.first_step else "rollout"
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    async with common.connect(engine) as server:
        if prior is None:
            info = common.stage_info(kind, args.set, args.model, [questions[i]["id"] for i in selected], samples,
                                     ollama, tools=server.tools, history=args.history, order=args.order,
                                     orders=orders, companies=common.demo_companies(engine),
                                     set_sha256=common.set_hash(questions), ollama_url=args.ollama_url, started=now)
        else:
            if prior.get("tools") != server.tools:
                common.fail(f"the tools as sent differ from {folder.name}'s (stage.json); start a new stage")
            if prior.get("ollama_version") != ollama.version():
                common.fail(f"{folder.name} ran on Ollama {prior.get('ollama_version')}, this is "
                            f"{ollama.version()}; sampling may differ, so start a new stage")
            info = {k: v for k, v in prior.items() if k != "stopped"}
            info["resumed"] = [*prior.get("resumed", []), now]
        common.write_stage(folder, info)
        checked = False

        def context_check():
            nonlocal checked
            if not checked:
                checked = True
                try:
                    common.check_context(ollama, args.model)
                except SystemExit:
                    common.write_stage(folder, {**info, "stopped": "context below 8192"})
                    raise

        started = time.monotonic()
        earlier = prior.get("seconds", 0) if prior else 0
        recorded = dict(done or {})

        def stop(reason: str) -> None:
            common.write_stage(folder, {**info, "stopped": reason,
                                        "seconds": round(earlier + time.monotonic() - started, 1)})
            print(f"stopped; {len(recorded)} samples are kept. Continue with: venv/bin/python scripts/mcp_eval/"
                  f"rollout.py {folder.name} --resume", file=sys.stderr)

        total = len(selected) * samples
        chain: list[tuple[str, str]] = []  # an `own` chain's (question, answer) pairs so far
        with (folder / "samples.jsonl").open("a", encoding="utf-8") as out:
            try:
                for k, i, order, row in planned(questions, selected, samples, args.history, orders):
                    question = questions[i]
                    if args.history == "own":
                        position = (order or [q["id"] for q in questions]).index(question["id"]) + 1
                        if position == 1:
                            chain = []
                        before = common.history_messages(chain)
                    elif args.history == "none":
                        before = []
                    else:
                        before = common.history(questions, i, order)
                    sample = recorded.get((question["id"], k))
                    if sample is None:
                        t0 = time.monotonic()
                        try:
                            ran = await rollout(ollama, server, args.model, before, question, args.first_step,
                                                context_check)
                        except (urllib.error.URLError, OSError, ValueError) as exc:
                            print(f"error: the Ollama request failed: {exc}", file=sys.stderr)
                            stop(f"Ollama request failed: {exc}")
                            return 1
                        sample = {"question": question["id"], "sample": k,
                                  **({"row": row} if row is not None else {}),
                                  **({"chain": k, "position": position} if args.history == "own" else {}),
                                  "seconds": round(time.monotonic() - t0, 2), **ran}
                        out.write(json.dumps(sample, ensure_ascii=False) + "\n")
                        out.flush()
                        recorded[(question["id"], k)] = sample
                        state = {True: "answered", False: "unanswered", None: "first step"}[sample["answered"]]
                        print(f"  {question['id']} sample {k}: {state}, {len(sample['exchanges'])} requests, "
                              f"{sample['seconds']:.0f}s ({len(recorded)}/{total})", file=sys.stderr)
                    if args.history == "own":
                        answer = final_answer(sample)
                        if answer is not None:
                            chain.append((question["text"], answer))
            except SystemExit:
                raise  # the context check wrote its own reason
            except BaseException:  # Ctrl-C (or a cancelled task): keep what's recorded, say how to go on
                stop("interrupted")
                raise
        common.write_stage(folder, {**info, "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                    "seconds": round(earlier + time.monotonic() - started, 1)})
    return 0


# --- the fidelity check ---


def _first_difference(built, captured, where: str) -> list[str]:
    if built == captured:
        return []
    if isinstance(built, dict) and isinstance(captured, dict):
        out = []
        for key in sorted(set(built) | set(captured)):
            if key not in captured:
                out.append(f"{where}.{key}: only in the rollout's request")
            elif key not in built:
                out.append(f"{where}.{key}: only in the captured request")
            else:
                out += _first_difference(built[key], captured[key], f"{where}.{key}")
        return out
    if isinstance(built, list) and isinstance(captured, list):
        for i, (a, b) in enumerate(zip(built, captured, strict=False)):
            if a != b:
                return _first_difference(a, b, f"{where}[{i}]")
        return [f"{where}: {len(built)} items in the rollout's request, {len(captured)} captured"]
    if isinstance(built, str) and isinstance(captured, str):
        at = next((i for i, (a, b) in enumerate(zip(built, captured, strict=False)) if a != b),
                  min(len(built), len(captured)))
        return [f"{where}: differs at character {at}: rollout {built[at:at + 60]!r}, captured {captured[at:at + 60]!r}"]
    return [f"{where}: rollout {json.dumps(built)[:80]}, captured {json.dumps(captured)[:80]}"]


def compare_request(built: dict, captured: dict) -> list[str]:
    """The differences between a built request and a captured one in tools, options and messages (and model and
    think); `stream` isn't compared (rollouts don't stream)."""
    out = []
    for key in ("model", "options", "think", "tools", "messages"):
        out += _first_difference(built.get(key), captured.get(key), key)
    return out


async def check(capture: Path, engine) -> tuple[int, list[str]]:
    """Replay a session capture's requests as ollmcp builds them; (requests compared, lines of the report)."""
    exchanges = score.session_exchanges(capture)
    lines, compared, differing = [], 0, 0
    chat_history: list[tuple[str, str]] = []
    state = None
    async with common.connect(engine) as server:
        for n, (captured, reply) in enumerate(exchanges, start=1):
            messages = captured.get("messages") or []
            last = messages[-1] if messages else {}
            if state is not None and last.get("role") == "user" and last.get("content") != state["query"]:
                lines.append(f"note: request {n} starts a new question before the last one ended; that one is "
                             "taken as stopped by the user (not kept in the history)")
                state = None
            if state is None:
                if last.get("role") != "user":
                    lines.append(f"request {n}: expected a new question, but its last message is {last.get('role')!r}")
                    differing += 1
                    break
                built_messages = common.history_messages(chat_history)
                built_messages.append({"role": "user", "content": last["content"]})
                state = {"query": last["content"], "messages": built_messages, "loops": 0, "response": "",
                         "number": len(chat_history) + 1}
            built = common.request_body(captured.get("model"), state["messages"], server.tools,
                                        stream=captured.get("stream", False))
            differences = compare_request(built, captured)
            compared += 1
            label = f"request {n} (question {state['number']}, loop {state['loops']})"
            if differences:
                differing += 1
                lines.append(f"{label}: differs")
                lines += [f"   {line}" for line in differences[:10]]
            else:
                lines.append(f"{label}: equal")
            if reply.get("content"):
                state["response"] = reply["content"]
            calls = reply.get("tool_calls") or []
            if not calls:
                chat_history.append((state["query"], state["response"]))
                state = None
            elif state["loops"] >= common.LOOP_LIMIT:
                state = None  # the client asks the user; the session driver stops the question
            else:
                state["loops"] += 1
                state["messages"] = state["messages"] + [common.assistant_message(reply)]
                for call in calls:
                    content = await server.answer(call)
                    if content is not None:
                        state["messages"].append(common.tool_message(call["function"]["name"], content))
    lines.append(f"{compared - differing} of {compared} requests equal")
    return differing, lines


# --- command ---


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("stage", nargs="?", help="the new stage's name (a folder under data/mcp-eval/stages/)")
    parser.add_argument("--set", choices=common.SETS, help="the question set (dev)")
    parser.add_argument("--questions", help="only these question ids, comma-separated (the history stays the set's)")
    parser.add_argument("--samples", type=int,
                        help=f"rollouts a question ({FULL_SAMPLES}; {FIRST_STEP_SAMPLES} with --first-step)")
    parser.add_argument("--first-step", action="store_true",
                        help="send only each question's first request (not with --history own)")
    parser.add_argument("--history", choices=common.HISTORIES,
                        help="what each question is asked after: fixed (the earlier questions with their written "
                             "answers; the default), own (chains: the model's own answers; the whole set, no "
                             "--questions or --first-step) or none (the question alone)")
    parser.add_argument("--order", choices=common.ORDERS,
                        help="set (the set's order; the default) or balanced (a Williams design over the set, for "
                             "one-off evaluations; not with --history none)")
    parser.add_argument("--model", help=f"the Ollama model ({common.DEFAULT_MODEL})")
    parser.add_argument("--resume", action="store_true",
                        help="continue a stopped rollout stage with its own options, running only the samples it "
                             "hasn't recorded (refused when the code, questions, tools or Ollama version changed)")
    parser.add_argument("--ollama-url", default=common.DEFAULT_OLLAMA,
                        help=f"a loopback Ollama address ({common.DEFAULT_OLLAMA})")
    parser.add_argument("--db", default=common.default_db_url(), help="the demo database (data/mcp-eval/demo)")
    parser.add_argument("--dry-run", action="store_true", help="state what would be sent, and send nothing")
    parser.add_argument("--check", type=Path, metavar="CAPTURE",
                        help="compare a real session's capture with the requests a rollout builds")
    parser.add_argument("--stages-dir", type=Path, default=common.STAGES, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.check:
        common.ensure_demo(args.db)
        engine = common.open_demo(args.db)
        if not args.check.is_file():
            common.fail(f"no capture at {args.check}")
        differing, lines = common.run_async(check, args.check, engine)
        engine.dispose()
        print("\n".join(lines))
        return 1 if differing else 0

    if not args.stage:
        parser.error("give a stage name, or --check CAPTURE")
    ollama = common.Ollama(args.ollama_url)  # refuses anything but loopback before anything is sent
    prior = None
    if args.resume:
        folder = common.stage_folder(args.stage, args.stages_dir)
        prior = resumed_info(folder, args)
    else:
        args.set = args.set or "dev"
        args.model = args.model or common.DEFAULT_MODEL
        args.history = args.history or "fixed"
        args.order = args.order or "set"
        if args.order == "balanced" and args.history == "none":
            common.fail("--order balanced needs a history: with --history none the order changes nothing")
        if args.history == "own" and args.questions:
            common.fail("--history own asks the whole set in each chain; --questions would change the history of "
                        "the questions it keeps")
        if args.history == "own" and args.first_step:
            common.fail("--history own can't run single steps: a question's first request needs the chain's "
                        "earlier answers")
    common.ensure_demo(args.db)
    engine = common.open_demo(args.db)
    questions = common.load_set(args.set)["questions"]
    if prior is not None:
        if prior.get("set_sha256") and prior["set_sha256"] != common.set_hash(questions):
            common.fail(f"the {args.set} set's questions or history answers changed since {args.stage} started; "
                        "start a new stage")
        done = done_samples(folder)
    else:
        done = {}
    ids = [question["id"] for question in questions]
    wanted = args.questions.split(",") if args.questions else ids
    unknown = [qid for qid in wanted if qid not in ids]
    if unknown:
        common.fail(f"not in the {args.set} set: {', '.join(unknown)}")
    selected = [ids.index(qid) for qid in wanted]
    samples = args.samples or (FIRST_STEP_SAMPLES if args.first_step else FULL_SAMPLES)
    if samples < 1:
        common.fail("--samples must be at least 1")
    orders = None
    if args.order == "balanced":
        orders = prior["orders"] if prior is not None else common.williams(ids)
    print(statement(args, [questions[i] for i in selected], samples, orders, len(done)))
    if args.dry_run:
        print("dry run: nothing sent")
        engine.dispose()
        return 0
    if prior is None:
        folder = common.new_stage(args.stage, args.stages_dir)
    try:
        return common.run_async(run_stage, args, engine, questions, selected, samples, folder, ollama, orders, prior,
                                done)
    except KeyboardInterrupt:
        return 130
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
