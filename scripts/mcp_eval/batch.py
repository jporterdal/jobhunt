"""Session batches of the MCP measurement (docs/mcp-eval.md): fresh ollmcp sessions of a question set, each through its
own capture proxy, against `jobhunt mcp` on the demo database from the working tree.

    venv/bin/python scripts/mcp_eval/batch.py STAGE --runs 3 [--set dev] [--model qwen3:8b]
        [--ollama-url http://127.0.0.1:11434] [--listen 127.0.0.1:11436] [--db URL] [--dry-run]

Each run starts `scripts/ollama_capture.py` (LISTEN -> the Ollama address) and `session.py` with the client as
docs/mcp.md starts it (`ollmcp --provider ollama --host http://LISTEN --model MODEL --servers-json FILE`, ollmcp
0.35.1 from data/mcp-eval/ollmcp-venv), which types the questions, answers `y` to each tool confirmation and aborts a
question at the loop limit. Output: data/mcp-eval/stages/STAGE/stage.json and run<k>/ (capture.jsonl,
session.raw, session.conns.json, driver.out, questions.txt, jobhunt-demo.json), scored by score.py like rollouts.
A session's history is its own earlier answers in the set's order, so its stage is recorded as history `own`.

Demo database only, loopback addresses only; it states the sessions first, and --dry-run stops there. The sessions
use the working tree's jobhunt (editable install), so don't edit src/ while a batch runs.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
from ollama_capture import DEFAULT_LISTEN, parse_listen  # noqa: E402

CAPTURE_SCRIPT = common.REPO / "scripts" / "ollama_capture.py"
SESSION_SCRIPT = common.HERE / "session.py"


def servers_json(db: str) -> dict:
    jobhunt = Path(sys.executable).parent / "jobhunt"
    return {"mcpServers": {common.SERVER: {
        "command": str(jobhunt), "args": ["mcp", "--db", db, "--share", ",".join(common.SCOPES)], "disabled": False,
    }}}


def client_command(listen: str, model: str, config: Path) -> list[str]:
    """The client's command line, as docs/mcp.md gives it, with the host pointed at the capture proxy."""
    return [str(common.OLLMCP), "--provider", "ollama", "--host", f"http://{listen}", "--model", model,
            "--servers-json", str(config)]


def statement(args, questions: list[dict]) -> str:
    ids = ", ".join(question["id"] for question in questions)
    return (f"session stage {args.stage}: {args.runs} ollmcp {common.OLLMCP_VERSION} sessions of the {args.set} set "
            f"with {args.model}, one code version (the working tree, code {common.code_hash()[:12]})\n"
            f"  {len(questions)} questions a session ({ids}), each tool call confirmed, up to "
            f"{common.LOOP_LIMIT} loops a question; Ollama at {args.ollama_url} through a capture proxy on "
            f"{args.listen}")


def _reachable(listen: str, seconds: float = 10) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with opener.open(f"http://{listen}/api/version", timeout=2):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def _has_chat(capture: Path) -> bool:
    try:
        return '"path": "/api/chat"' in capture.read_text(encoding="utf-8")
    except OSError:
        return False


def run_session(k: int, folder: Path, args, questions: list[dict], ollama: common.Ollama, check_context) -> int:
    """One session; the number of questions it finished."""
    run = folder / f"run{k}"
    run.mkdir()
    (run / "questions.txt").write_text("".join(q["text"] + "\n" for q in questions), encoding="utf-8")
    config = run / "jobhunt-demo.json"
    config.write_text(json.dumps(servers_json(args.db), indent=1) + "\n", encoding="utf-8")
    capture = run / "capture.jsonl"
    with (run / "capture.log").open("w") as log:
        proxy = subprocess.Popen([sys.executable, "-I", str(CAPTURE_SCRIPT), "--out", str(capture),
                                  "--listen", args.listen, "--upstream", ollama.base], stderr=log)
    try:
        if not _reachable(args.listen):
            common.fail(f"the capture proxy on {args.listen} didn't start (see {run / 'capture.log'})")
        capture.write_text("")  # drop the readiness request
        with (run / "driver.out").open("w") as out:
            session = subprocess.Popen(
                [sys.executable, str(SESSION_SCRIPT), str(run / "session"), str(run / "questions.txt"),
                 *client_command(args.listen, args.model, config)],
                cwd=run, stdout=out, stderr=subprocess.STDOUT,
            )
            checked = False
            while session.poll() is None:
                if not checked and _has_chat(capture):
                    checked = True
                    try:
                        check_context()
                    except SystemExit:
                        session.terminate()
                        session.wait()
                        raise
                time.sleep(1)
    finally:
        proxy.terminate()
        proxy.wait()
    done = (run / "driver.out").read_text(encoding="utf-8").count("question done=True")
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("stage", help="the new stage's name (a folder under data/mcp-eval/stages/)")
    parser.add_argument("--runs", type=int, required=True, help="how many sessions")
    parser.add_argument("--set", choices=common.SETS, default="dev", help="the question set (dev)")
    parser.add_argument("--model", default=common.DEFAULT_MODEL, help=f"the Ollama model ({common.DEFAULT_MODEL})")
    parser.add_argument("--ollama-url", default=common.DEFAULT_OLLAMA,
                        help=f"a loopback Ollama address ({common.DEFAULT_OLLAMA})")
    parser.add_argument("--listen", default=DEFAULT_LISTEN, help=f"the capture proxy's loopback address "
                                                                f"({DEFAULT_LISTEN})")
    parser.add_argument("--db", default=common.default_db_url(), help="the demo database (data/mcp-eval/demo)")
    parser.add_argument("--dry-run", action="store_true", help="state the sessions, and start nothing")
    parser.add_argument("--stages-dir", type=Path, default=common.STAGES, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    ollama = common.Ollama(args.ollama_url)
    try:
        parse_listen(args.listen)
    except ValueError as exc:
        common.fail(str(exc))
    if args.runs < 1:
        common.fail("--runs must be at least 1")
    common.ensure_demo(args.db)
    engine = common.open_demo(args.db)
    companies = common.demo_companies(engine)
    engine.dispose()
    questions = common.load_set(args.set)["questions"]
    print(statement(args, questions))
    if not common.OLLMCP.exists():
        message = f"no ollmcp at {common.OLLMCP}; make its venv as docs/mcp-eval.md says"
        if not args.dry_run:
            common.fail(message)
        print(f"note: {message}")
    if args.dry_run:
        print("dry run: nothing started")
        return 0

    folder = common.new_stage(args.stage, args.stages_dir)
    info = common.stage_info("session", args.set, args.model, [q["id"] for q in questions], args.runs, ollama,
                             history="own", companies=companies, ollama_url=args.ollama_url,
                             started=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    common.write_stage(folder, info)

    def check_context():
        try:
            common.check_context(ollama, args.model)
        except SystemExit:
            common.write_stage(folder, {**info, "stopped": "context below 8192"})
            raise

    started = time.monotonic()
    for k in range(1, args.runs + 1):
        done = run_session(k, folder, args, questions, ollama, check_context if k == 1 else lambda: None)
        print(f"{args.stage} run{k}: {done}/{len(questions)} finished")
    common.write_stage(folder, {**info, "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                "seconds": round(time.monotonic() - started, 1)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
