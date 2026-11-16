"""Rollouts of the MCP measurement (docs/mcp-eval.md): each question answered the way the documented client (ollmcp
0.35.1) would answer it, without the client, sampled many times from a fixed history.

    venv/bin/python scripts/mcp_eval/rollout.py STAGE [--set dev] [--questions dev-2,dev-3] [--samples 10]
        [--first-step] [--model qwen3:8b] [--ollama-url http://127.0.0.1:11434] [--db URL] [--dry-run]
    venv/bin/python scripts/mcp_eval/rollout.py STAGE --resume [--ollama-url URL] [--db URL] [--dry-run]
    venv/bin/python scripts/mcp_eval/rollout.py --check CAPTURE [--db URL]

A rollout of a question sends Ollama the requests the client sends: the tools listed by the working tree's server and
rendered as the client renders them, the client's options, the earlier questions of the set with their written
`history_answer`s, then the question; each tool call is answered by calling the working tree's server in-process
(through the SDK's in-memory client, so arguments are sifted as in a session) and passed on as the client passes it;
it stops at an answer or after the client's 7 loops (unanswered). Only `stream` differs from the client (false: the
same sampling, one reply to record). `--first-step` sends only each question's first request and records its tool
calls. Every request, reply and tool result goes to data/mcp-eval/stages/STAGE/samples.jsonl, and what ran to
stage.json (with copies of mcp_server.py and mcp_tools.py). Each sample is written as it finishes, so a stage
stopped (Ctrl-C, a failed request, a reboot) keeps what it recorded; `--resume` runs the samples it lacks, with the
stage's own options, and is refused when the code, the set's questions, the tools or the Ollama version changed.

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


async def rollout(ollama: common.Ollama, server: common.Server, model: str, questions: list[dict], index: int,
                  first_step: bool = False, on_request=None) -> dict:
    """One rollout of questions[index]: {answered (None for a single step), loops, exchanges, results}."""
    messages = common.history(questions, index) + [{"role": "user", "content": questions[index]["text"]}]
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


def statement(args, questions: list[dict], samples: int, done: int = 0) -> str:
    kind = "single-step rollouts (each question's first request only)" if args.first_step else "full rollouts"
    most = 1 if args.first_step else common.LOOP_LIMIT + 1
    ids = ", ".join(question["id"] for question in questions)
    total = len(questions) * samples
    resuming = f"\n  resuming: {done} recorded, {total - done} left to run" if args.resume else ""
    return (f"rollout stage {args.stage}: {kind} of the {args.set} set with {args.model}, one code version (the "
            f"working tree, code {common.code_hash()[:12]})\n"
            f"  {len(questions)} questions ({ids}) x {samples} samples = {total} rollouts, "
            f"up to {most} request{'s' if most > 1 else ''} each, to Ollama at {args.ollama_url}{resuming}")


def done_samples(folder: Path) -> set[tuple[str, int]]:
    """The (question, sample) pairs a stopped stage already recorded. A last line cut off by a kill is removed from
    samples.jsonl, so the stage reads cleanly and that sample runs again."""
    path = folder / "samples.jsonl"
    if not path.exists():
        return set()
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        data = data[:data.rfind(b"\n") + 1]
        path.write_bytes(data)
        print("note: removed a sample cut off when the stage stopped; it runs again", file=sys.stderr)
    done = set()
    for line in data.decode("utf-8").splitlines():
        sample = json.loads(line)
        done.add((sample["question"], sample["sample"]))
    return done


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
    given = {"--set": args.set, "--questions": args.questions, "--samples": args.samples, "--model": args.model}
    given = [option for option, value in given.items() if value is not None] + (["--first-step"] * args.first_step)
    if given:
        common.fail(f"--resume takes the stage's own options; leave out {', '.join(given)}")
    args.set, args.model, args.samples = info["set"], info["model"], info["samples"]
    args.questions, args.first_step = ",".join(info["questions"]), info["kind"] == "first-step"
    if info.get("code_sha256") != common.code_hash():
        common.fail(f"mcp_server.py or mcp_tools.py changed since {folder.name} started (its copies are in "
                    f"{folder / 'code'}); restore them to resume, or start a new stage")
    return info


async def run_stage(args, engine, questions: list[dict], selected: list[int], samples: int, folder: Path,
                    ollama: common.Ollama, prior: dict | None = None, done: frozenset = frozenset()) -> int:
    kind = "first-step" if args.first_step else "rollout"
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    async with common.connect(engine) as server:
        if prior is None:
            info = common.stage_info(kind, args.set, args.model, [questions[i]["id"] for i in selected], samples,
                                     ollama, tools=server.tools, companies=common.demo_companies(engine),
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

        def stop(reason: str) -> None:
            common.write_stage(folder, {**info, "stopped": reason,
                                        "seconds": round(earlier + time.monotonic() - started, 1)})
            print(f"stopped; {len(done)} samples are kept. Continue with: venv/bin/python scripts/mcp_eval/"
                  f"rollout.py {folder.name} --resume", file=sys.stderr)

        done = set(done)
        with (folder / "samples.jsonl").open("a", encoding="utf-8") as out:
            try:
                for k in range(1, samples + 1):  # interleaved, so a stage stopped early is even across questions
                    for i in selected:
                        if (questions[i]["id"], k) in done:
                            continue
                        t0 = time.monotonic()
                        try:
                            sample = await rollout(ollama, server, args.model, questions, i, args.first_step,
                                                   context_check)
                        except (urllib.error.URLError, OSError, ValueError) as exc:
                            print(f"error: the Ollama request failed: {exc}", file=sys.stderr)
                            stop(f"Ollama request failed: {exc}")
                            return 1
                        sample = {"question": questions[i]["id"], "sample": k,
                                  "seconds": round(time.monotonic() - t0, 2), **sample}
                        out.write(json.dumps(sample, ensure_ascii=False) + "\n")
                        out.flush()
                        done.add((questions[i]["id"], k))
                        state = {True: "answered", False: "unanswered", None: "first step"}[sample["answered"]]
                        print(f"  {questions[i]['id']} sample {k}: {state}, {len(sample['exchanges'])} requests, "
                              f"{sample['seconds']:.0f}s ({len(done)}/{len(selected) * samples})", file=sys.stderr)
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
                built_messages = []
                for query, response in chat_history:
                    built_messages.append({"role": "user", "content": query})
                    if response:
                        built_messages.append({"role": "assistant", "content": response})
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
    parser.add_argument("--first-step", action="store_true", help="send only each question's first request")
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
    prior, done = None, set()
    if args.resume:
        folder = common.stage_folder(args.stage, args.stages_dir)
        prior = resumed_info(folder, args)
    else:
        args.set = args.set or "dev"
        args.model = args.model or common.DEFAULT_MODEL
    common.ensure_demo(args.db)
    engine = common.open_demo(args.db)
    questions = common.load_set(args.set)["questions"]
    if prior is not None:
        if prior.get("set_sha256") and prior["set_sha256"] != common.set_hash(questions):
            common.fail(f"the {args.set} set's questions or history answers changed since {args.stage} started; "
                        "start a new stage")
        done = done_samples(folder)
    ids = [question["id"] for question in questions]
    wanted = args.questions.split(",") if args.questions else ids
    unknown = [qid for qid in wanted if qid not in ids]
    if unknown:
        common.fail(f"not in the {args.set} set: {', '.join(unknown)}")
    selected = [ids.index(qid) for qid in wanted]
    samples = args.samples or (FIRST_STEP_SAMPLES if args.first_step else FULL_SAMPLES)
    if samples < 1:
        common.fail("--samples must be at least 1")
    print(statement(args, [questions[i] for i in selected], samples, len(done)))
    if args.dry_run:
        print("dry run: nothing sent")
        engine.dispose()
        return 0
    if prior is None:
        folder = common.new_stage(args.stage, args.stages_dir)
    try:
        return common.run_async(run_stage, args, engine, questions, selected, samples, folder, ollama, prior,
                                frozenset(done))
    except KeyboardInterrupt:
        return 130
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
