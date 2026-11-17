"""scripts/mcp_eval/ (docs/mcp-eval.md) without a model: the guards, the ollmcp rendering against a real capture of a
demo session, the question sets' expected facts against the demo, the checks, diagnostics and verdict, the held-out
refusal, and rollouts against a stub Ollama on loopback with the working tree's server in-process. The scripts are
loaded by path, as tests/test_ollama_capture.py loads its script. Skipped without the `mcp` extra."""

import json
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="the mcp extra isn't installed")

import anyio  # noqa: E402  (installed with mcp)

from jobhunt import mcp_server, mcp_tools  # noqa: E402
from jobhunt.db import init_db, make_engine  # noqa: E402
from jobhunt.demo import seed  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts" / "mcp_eval"
sys.path.insert(0, str(SCRIPTS))

import batch  # noqa: E402
import common  # noqa: E402
import compare  # noqa: E402
import detail  # noqa: E402
import rollout  # noqa: E402
import score  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mcp_eval" / "session-capture.jsonl"
MODEL = "qwen3:8b"


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    """The URL of a demo database built for this module."""
    folder = tmp_path_factory.mktemp("mcp-eval-demo")
    engine = make_engine(f"sqlite:///{folder / 'jobhunt.db'}")
    init_db(engine)
    seed.build(engine, folder / "documents")
    engine.dispose()
    return f"sqlite:///{folder / 'jobhunt.db'}"


@pytest.fixture
def demo_engine(demo):
    engine = common.open_demo(demo)
    yield engine
    engine.dispose()


def exits_2(call, *args):
    with pytest.raises(SystemExit) as raised:
        call(*args)
    assert raised.value.code == 2


# --- a stub Ollama on loopback ---


class StubOllama(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    script = None  # request body -> reply
    seen: list = []
    context = 8192

    def log_message(self, *args):
        pass

    def _send(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/ps":
            self._send({"models": [{"name": MODEL, "model": MODEL, "context_length": type(self).context}]})
        else:
            self._send({"version": "0.0-stub"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append(body)
        self._send(type(self).script(body))


def reply(content="", calls=()):
    message = {"role": "assistant", "content": content, "thinking": "Thinking about it."}
    if calls:
        message["tool_calls"] = [{"id": f"call_{i}", "function": {"index": i, "name": name, "arguments": arguments}}
                                 for i, (name, arguments) in enumerate(calls)]
    return {"model": MODEL, "message": message, "done": True, "done_reason": "stop", "prompt_eval_count": 1200}


@pytest.fixture
def stub():
    StubOllama.seen = []
    StubOllama.context = 8192
    StubOllama.script = lambda body: reply("An answer.")
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def run_rollouts(stub, demo, stages, *extra):
    return rollout.main(["stage", "--db", demo, "--ollama-url", stub, "--stages-dir", str(stages), *extra])


def samples_of(folder):
    return [json.loads(line) for line in (folder / "samples.jsonl").read_text().splitlines()]


# --- guards (1.1) ---


def test_a_database_not_built_by_jobhunt_demo_is_refused(tmp_path, capsys):
    engine = make_engine(f"sqlite:///{tmp_path / 'own.db'}")
    init_db(engine)
    engine.dispose()
    exits_2(common.open_demo, f"sqlite:///{tmp_path / 'own.db'}")
    assert "demo only" in capsys.readouterr().err


def test_a_missing_database_is_refused_and_not_created(tmp_path):
    exits_2(common.open_demo, f"sqlite:///{tmp_path / 'none.db'}")
    assert not (tmp_path / "none.db").exists()


def test_the_demo_is_accepted_read_only(demo):
    engine = common.open_demo(demo)
    with pytest.raises(Exception, match="readonly"), engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM postings")
    engine.dispose()


@pytest.mark.parametrize("url", ["http://gpu.example.com:11434", "http://10.0.0.5:11434", "https://127.0.0.1:11434"])
def test_only_a_loopback_ollama_is_accepted(url):
    exits_2(common.ollama_base, url)


def test_rollouts_refuse_a_remote_ollama_and_a_non_demo_database_before_sending(stub, demo, tmp_path):
    exits_2(run_rollouts, "http://gpu.example.com:11434", demo, tmp_path)
    engine = make_engine(f"sqlite:///{tmp_path / 'own.db'}")
    init_db(engine)
    engine.dispose()
    exits_2(run_rollouts, stub, f"sqlite:///{tmp_path / 'own.db'}", tmp_path)
    assert StubOllama.seen == [] and not (tmp_path / "stage").exists()


# --- the client's rendering (1.2) ---


def captured():
    return score.session_exchanges(FIXTURE)


def test_tools_are_rendered_as_the_client_sends_them(demo_engine):
    async def tools():
        async with common.connect(demo_engine) as server:
            return server.tools

    rendered = anyio.run(tools)
    for request, _ in captured():
        assert request["tools"] == rendered
    search = rendered[0]["function"]
    assert search["name"] == "jobhunt_search_postings" and search["description"].startswith("[jobhunt] Search")
    assert "title" not in search["parameters"] and "default" not in search["parameters"]["properties"]["q"]


def test_tool_results_are_passed_on_as_the_client_passes_them(demo_engine):
    exchanges = captured()

    async def replay():
        compared = 0
        async with common.connect(demo_engine) as server:
            for (request, reply_), (following, _) in zip(exchanges, exchanges[1:], strict=False):
                calls = reply_["tool_calls"]
                if not calls:
                    continue
                at = len(request["messages"])
                assert following["messages"][at] == common.assistant_message(reply_)
                for i, call in enumerate(calls):
                    message = common.tool_message(call["function"]["name"], await server.answer(call))
                    assert following["messages"][at + 1 + i] == message
                    compared += 1
        return compared

    assert anyio.run(replay) == 9  # an error result and an argument outside the schema among them


def test_an_unknown_tool_gets_no_tool_message(demo_engine):
    async def answer():
        async with common.connect(demo_engine) as server:
            return [await server.answer({"function": {"name": name, "arguments": {}}})
                    for name in ("search_postings", "jobhunt_nothing", "other.search_postings")]

    assert anyio.run(answer) == [None, None, None]


def test_history_holds_earlier_questions_and_their_answers():
    questions = common.load_set("dev")["questions"]
    messages = common.history(questions, 2)
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[1]["content"] == questions[0]["history_answer"]


# --- question sets and their expected facts (2.1-2.3) ---


def test_the_sets_are_disjoint_and_written_in_their_own_layout():
    dev, holdout = common.load_set("dev"), common.load_set("holdout")
    assert not {q["id"] for q in dev["questions"]} & {q["id"] for q in holdout["questions"]}
    assert [q["id"] for q in holdout["questions"]] == [f"holdout-{n}" for n in range(1, 6)]
    for name in common.SETS:
        text = common.set_path(name).read_text(encoding="utf-8")
        assert common.dump_set(json.loads(text)) == text


def source_results(engine, question) -> list:
    out = []
    with engine.connect() as conn:
        for source in question["sources"]:
            out.append(mcp_tools.TOOLS[source["tool"]](conn, **source["arguments"]))
    return out


def numbers_in(value) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, int | float):
        return [value]
    if isinstance(value, dict):
        return [n for v in value.values() for n in numbers_in(v)]
    if isinstance(value, list):
        return [n for v in value for n in numbers_in(v)]
    return []


def fact_problems(engine, question) -> list[str]:
    """Each expected fact of a question that the tools' results for its sources don't hold."""
    results = source_results(engine, question)
    text = json.dumps(results, ensure_ascii=False)
    urls = score.url_numbers(text)
    numbers = numbers_in(results)
    amounts = score.result_numbers([text])
    problems = []
    for check in question["checks"]:
        kind = check["kind"]
        if kind == "answer_urls" and "exact" in check and set(check["exact"]) != urls:
            problems.append(f"answer_urls exact {sorted(check['exact'])}: the tools give {sorted(urls)}")
        if kind == "answer_urls" and "includes" in check and not set(check["includes"]) <= urls:
            problems.append(f"answer_urls includes {check['includes']}: the tools give {sorted(urls)}")
        for value in check.get("values", []) if kind == "answer_figures" else []:
            if not any(abs(n - value) < 1e-6 for n in numbers):
                problems.append(f"answer_figures {value}: no such figure in the tools' results")
        for name in check.get("names", []) if kind == "answer_mentions" else []:
            if not score.mentions(text, name):
                problems.append(f"answer_mentions {name!r}: not in the tools' results")
        for amount in check.get("amounts", []) if kind == "answer_amounts" else []:
            if amount not in amounts:
                problems.append(f"answer_amounts {amount}: not in the tools' results")
        if kind in ("called", "first_call") and check.get("arguments") is not None:
            with engine.connect() as conn:
                try:
                    result = mcp_tools.TOOLS[check["tool"]](conn, **check["arguments"])
                except mcp_tools.NotFound as exc:
                    problems.append(f"{kind} {check['tool']} {check['arguments']}: {exc}")
                    continue
            if "job_id" in check["arguments"] and not score.url_numbers(json.dumps(result)) & expected_urls(question):
                problems.append(f"{kind} {check['tool']} {check['arguments']}: not the posting the question names")
    return problems


def expected_urls(question) -> set[str]:
    return {n for check in question["checks"] if check["kind"] == "answer_urls"
            for n in check.get("exact", []) + check.get("includes", [])}


@pytest.mark.parametrize("set_name", common.SETS)
def test_expected_facts_hold_on_the_demo(demo_engine, set_name):
    problems = {q["id"]: fact_problems(demo_engine, q) for q in common.load_set(set_name)["questions"]}
    assert {qid: found for qid, found in problems.items() if found} == {}


def test_a_changed_figure_is_named_with_its_question(demo_engine):
    question = next(q for q in common.load_set("dev")["questions"] if q["id"] == "dev-3")
    changed = json.loads(json.dumps(question))
    next(c for c in changed["checks"] if c["kind"] == "answer_figures")["values"] = [0.7]
    assert fact_problems(demo_engine, changed) == ["answer_figures 0.7: no such figure in the tools' results"]


# --- checks and diagnostics (3.1) ---

DEV = {q["id"]: q for q in common.load_set("dev")["questions"]}
SCHEMAS = {"search_postings": {"q", "tag", "workplace", "dismissed", "limit"}, "get_posting": {"job_id"},
           "posting_fit": {"job_id"}, "recommendations": {"workplace"}, "profile_skills": set()}


def record(answer="", calls=(), results=(), answered=True, first=None):
    made = [{"name": common.wire_name(tool), "tool": tool, "arguments": arguments} for tool, arguments in calls]
    return {"calls": made, "first_calls": made[:1] if first is None else first, "results": list(results),
            "answer": answer, "answered": answered, "tokens": 900, "replies": 2, "schemas": SCHEMAS}


ML_RESULT = '{\n  "job_id": 1,\n  "description": "Salary: $105,000–$125,000 CAD per year"\n}'
ML_URL = "https://jobs.example.com/view/9000000101"


def test_the_ml_engineer_answer_passes_with_its_link_and_pay():
    sample = score.score_sample(record(f"It pays $105,000–$125,000: {ML_URL}", [("get_posting", {"job_id": 1})],
                                       [ML_RESULT]), DEV["dev-2"], [], "rollout")
    assert sample["passed"] and sample["checks"] == [True, True]
    assert not any(sample["diagnostics"].values())


def test_a_made_up_salary_fails_and_is_counted():
    sample = score.score_sample(record(f"It pays $140,000 a year: {ML_URL}", [("get_posting", {"job_id": 1})],
                                       [ML_RESULT]), DEV["dev-2"], [], "rollout")
    assert not sample["passed"] and sample["diagnostics"]["made_up_amount"] == 1


@pytest.mark.parametrize("text, amounts", [
    ("$105,000–$125,000 CAD", {105000, 125000}),
    ("between 105,000 and 125,000", {105000, 125000}),
    ("$105k to $125K", {105000, 125000}),
    ("$105000 - 125k", {105000, 125000}),
    ("posting 9000000101, 3 skills, $12.50", set()),
])
def test_money_amounts(text, amounts):
    assert score.money_amounts(text) == amounts


@pytest.mark.parametrize("check, answer, passes", [
    ({"kind": "answer_urls", "exact": ["9000000101"]}, f"{ML_URL}", True),
    ({"kind": "answer_urls", "exact": ["9000000101"]}, f"{ML_URL} and .../view/9000000110", False),
    ({"kind": "answer_urls", "includes": ["9000000101"]}, f"{ML_URL} and .../view/9000000110", True),
    ({"kind": "answer_figures", "values": [0.644375]}, "a score of 64%", True),
    ({"kind": "answer_figures", "values": [0.644375]}, "a score of 0.644", True),
    ({"kind": "answer_figures", "values": [0.644375]}, "a score of 0.66", False),
    ({"kind": "answer_mentions", "names": ["Master's degree"]}, "a master’s degree", True),
    ({"kind": "answer_mentions", "names": ["dbt"]}, "nothing missing", False),
])
def test_answer_checks(check, answer, passes):
    assert score.check_passes(check, record(answer)) is passes


def test_call_checks():
    fit = {"kind": "called", "tool": "posting_fit", "arguments": {"job_id": 3}}
    assert score.check_passes(fit, record(calls=[("search_postings", {"q": "x"}), ("posting_fit", {"job_id": 3})]))
    assert not score.check_passes(fit, record(calls=[("posting_fit", {"job_id": 9000000103})]))
    first = {"kind": "first_call", "tool": "search_postings", "arguments": {"q": "Example Labs"}, "without": ["tag"]}
    assert score.check_passes(first, record(calls=[("search_postings", {"q": "example labs"})]))
    assert not score.check_passes(first, record(calls=[("search_postings", {"q": "Example Labs", "tag": "x"})]))
    assert not score.check_passes(first, record(calls=[]))


def test_diagnostics_of_one_sample():
    sample = record(
        "No answer with figures.",
        calls=[("search_postings", {"q": "Senior Data Analyst Example Insurance", "workplace": "Remote"}),
               ("get_posting", {"job_id": 9000000103}), ("search_postings", {"q": "x", "company": "Example"}),
               ("nothing", {})],
        results=['{\n  "warnings": [\n    "`company` is not an argument"\n  ],\n  "total": 0\n}',
                 "Error executing tool get_posting: No posting with id 9000000103."],
        answered=False,
    )
    seen = score.diagnostics(sample, DEV["dev-3"], ["Example Insurance", "Example Labs"], "rollout")
    assert seen == {"url_as_job_id": 1, "combined_q": 1, "invented_args": 1, "unknown_tool": 1, "carried_filter": 1,
                    "made_up_amount": 0, "refused": 1, "warnings": 1, "unanswered": 1}


def test_a_carried_filter_is_one_the_question_doesnt_ask_for():
    remote = record(calls=[("search_postings", {"workplace": "Remote"})])
    assert score.diagnostics(remote, DEV["dev-1"], [], "rollout")["carried_filter"] == 0
    assert score.diagnostics(remote, DEV["dev-2"], [], "rollout")["carried_filter"] == 1


def write_session_stage(folder: Path, info=None):
    (folder / "run1").mkdir(parents=True)
    shutil.copy(FIXTURE, folder / "run1" / "capture.jsonl")
    if info is not None:
        common.write_stage(folder, info)


def test_a_session_capture_is_scored_by_question(tmp_path, demo):
    write_session_stage(tmp_path / "legacy")
    scored = score.score_stage(score.load_stage(tmp_path / "legacy", db=demo))
    passed = {qid: q["passed"] for qid, q in scored["questions"].items()}
    assert passed == {"dev-1": 1, "dev-2": 1, "dev-3": 0, "dev-4": 1, "dev-5": 0}
    dev3 = scored["questions"]["dev-3"]
    assert dev3["checks"]["answer_urls"] == 1 and dev3["checks"]["called:posting_fit"] == 0
    assert {k for k, v in dev3["diagnostics"].items() if v} == {"url_as_job_id", "combined_q", "carried_filter",
                                                                "refused", "warnings"}
    assert scored["questions"]["dev-2"]["diagnostics"]["invented_args"] == 1
    assert scored["model"] == MODEL and (scored["all_passed"], scored["all_samples"]) == (0, 1)


def test_the_earlier_scorers_figures_on_its_runs(demo):
    """The earlier harness's runs, where they are on this machine (ignored data): the same pass counts."""
    runs = common.REPO / "data" / "mcp-smoke" / "runs"
    if not (runs / "q-substring").is_dir() or not (runs / "change2").is_dir():
        pytest.skip("no data/mcp-smoke/runs here")
    q_substring = score.score_stage(score.load_stage(runs / "q-substring", db=demo))
    change2 = score.score_stage(score.load_stage(runs / "change2", db=demo))
    assert q_substring["questions"]["dev-2"]["passed"] == 3 and q_substring["questions"]["dev-2"]["samples"] == 3
    assert change2["questions"]["dev-2"]["passed"] == 0 and change2["questions"]["dev-2"]["samples"] == 5


# --- verdict (3.2) ---


@pytest.mark.parametrize("a, b, p", [(2, 8, 0.0115), (2, 9, 0.0027), (6, 8, 0.314)])
def test_p_values(a, b, p):
    assert compare.p_more(a, 10, b, 10) == pytest.approx(p, abs=5e-4)
    assert compare.p_less(b, 10, a, 10) == pytest.approx(p, abs=5e-4)


def scored_stage(name, passes, kind="rollout"):
    return {"stage": name, "kind": kind, "set": "dev", "model": MODEL,
            "questions": {qid: {"passed": p, "samples": 10} for qid, p in passes.items()}}


def test_a_clear_improvement_is_better_for_the_question_and_the_set():
    result = compare.compare(scored_stage("a", {"dev-1": 10, "dev-2": 2}), scored_stage("b", {"dev-1": 10, "dev-2": 9}))
    assert result["questions"]["dev-2"]["verdict"] == "better"
    assert result["questions"]["dev-1"]["verdict"] == "within noise" and result["verdict"] == "better"


def test_small_differences_are_within_noise_and_any_worse_makes_the_set_worse():
    small = compare.compare(scored_stage("a", {"dev-2": 6}), scored_stage("b", {"dev-2": 8}))
    assert small["questions"]["dev-2"]["verdict"] == "within noise" and small["verdict"] == "within noise"
    mixed = compare.compare(scored_stage("a", {"dev-1": 2, "dev-2": 9}), scored_stage("b", {"dev-1": 9, "dev-2": 2}))
    assert mixed["verdict"] == "worse"


def test_stages_of_different_sets_models_or_kinds_are_refused():
    base = {"set": "dev", "kind": "rollout", "model": MODEL}
    assert compare.refusal(base, dict(base)) is None
    for key, other in (("set", "holdout"), ("kind", "first-step"), ("model", "qwen3:14b")):
        assert compare.refusal(base, {**base, key: other})
    notes = compare.warnings({**base, "code_sha256": "x", "ollama_version": "1"},
                             {**base, "code_sha256": "x", "ollama_version": "2"})
    assert any("same code" in n for n in notes) and any("Ollama versions" in n for n in notes)


# --- held-out questions (3.3) ---


@pytest.fixture
def question_copies(tmp_path):
    folder = tmp_path / "questions"
    shutil.copytree(common.QUESTIONS, folder)
    return folder


def holdout_stage(tmp_path, secret):
    folder = tmp_path / "held"
    folder.mkdir()
    common.write_stage(folder, {"kind": "rollout", "set": "holdout", "model": MODEL, "tools": []})
    question = common.load_set("holdout")["questions"][2]
    request = {"model": MODEL, "messages": [{"role": "user", "content": question["text"]}]}
    sample = {"question": question["id"], "sample": 1,
              "exchanges": [{"request": request, "reply": {"content": secret, "tool_calls": []}}]}
    (folder / "samples.jsonl").write_text(json.dumps(sample) + "\n")
    return folder


def test_a_held_out_question_is_refused_without_reveal(tmp_path, question_copies, capsys):
    folder = holdout_stage(tmp_path, "SECRET ANSWER")
    before = {p.name: p.read_text() for p in question_copies.iterdir()}
    exits_2(detail.main, [str(folder), "holdout-3", "--questions-dir", str(question_copies)])
    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err and "--reveal" in out.err
    assert {p.name: p.read_text() for p in question_copies.iterdir()} == before


def test_reveal_shows_it_and_moves_it_to_dev(tmp_path, question_copies, capsys):
    folder = holdout_stage(tmp_path, "SECRET ANSWER")
    assert detail.main([str(folder), "holdout-3", "--reveal", "--questions-dir", str(question_copies)]) == 0
    out = capsys.readouterr()
    assert "SECRET ANSWER" in out.out and "moved holdout-3" in out.err
    dev = common.load_set("dev", question_copies / "dev.json")
    holdout = common.load_set("holdout", question_copies / "holdout.json")
    assert dev["questions"][-1]["id"] == "holdout-3" and len(dev["questions"]) == 6
    assert "holdout-3" not in {q["id"] for q in holdout["questions"]} and len(holdout["questions"]) == 4


def test_a_dev_question_never_moves(tmp_path, question_copies):
    before = {p.name: p.read_text() for p in question_copies.iterdir()}
    write_session_stage(tmp_path / "s")
    assert detail.main([str(tmp_path / "s"), "dev-2", "--reveal", "--questions-dir", str(question_copies)]) == 0
    assert {p.name: p.read_text() for p in question_copies.iterdir()} == before


# --- rollouts (4.1-4.3) ---


def test_a_rollout_carries_the_working_trees_results_and_history(stub, demo, demo_engine, tmp_path):
    arguments = {"q": "Machine Learning Engineer", "workplace": "Remote"}
    StubOllama.script = lambda body: (reply("The answer.") if body["messages"][-1]["role"] == "tool"
                                      else reply(calls=[("jobhunt_search_postings", arguments)]))
    assert run_rollouts(stub, demo, tmp_path, "--questions", "dev-2", "--samples", "1") == 0
    first, second = StubOllama.seen
    dev = common.load_set("dev")["questions"]
    assert first["messages"] == common.history(dev, 1) + [{"role": "user", "content": dev[1]["text"]}]
    assert {k: first[k] for k in ("model", "stream", "options", "think")} == {
        "model": MODEL, "stream": False, "options": {}, "think": "medium"}

    async def expected():
        async with common.connect(demo_engine) as server:
            return await server.answer({"function": {"name": "jobhunt_search_postings", "arguments": arguments}})

    assert second["messages"][-2] == {"role": "assistant", "tool_calls": [
        {"function": {"name": "jobhunt_search_postings", "arguments": arguments}}]}
    assert second["messages"][-1] == common.tool_message("jobhunt_search_postings", anyio.run(expected))
    assert '"total_without"' in second["messages"][-1]["content"]
    [sample] = samples_of(tmp_path / "stage")
    assert sample["answered"] is True and len(sample["exchanges"]) == 2 and sample["results"][0]["content"]
    info = common.read_stage(tmp_path / "stage")
    assert info["kind"] == "rollout" and info["questions"] == ["dev-2"] and info["samples"] == 1
    assert info["ollama_version"] == "0.0-stub" and info["code_sha256"] == common.code_hash()
    assert info["tools"] == first["tools"] and "finished" in info
    assert (tmp_path / "stage" / "code" / "mcp_server.py").read_text() == common.CODE_FILES[0].read_text()


def test_a_rollout_carries_a_changed_description(stub, demo, tmp_path, monkeypatch):
    monkeypatch.setitem(mcp_server.DESCRIPTIONS, "search_postings", "Changed for a test.")
    assert run_rollouts(stub, demo, tmp_path, "--questions", "dev-1", "--samples", "1") == 0
    assert StubOllama.seen[0]["tools"][0]["function"]["description"] == "[jobhunt] Changed for a test."


def test_a_rollout_stops_at_the_loop_limit(stub, demo, tmp_path):
    StubOllama.script = lambda body: reply(calls=[("jobhunt_profile_skills", {})])
    assert run_rollouts(stub, demo, tmp_path, "--questions", "dev-4", "--samples", "1") == 0
    assert len(StubOllama.seen) == common.LOOP_LIMIT + 1
    [sample] = samples_of(tmp_path / "stage")
    assert sample["answered"] is False and sample["loops"] == common.LOOP_LIMIT
    scored = score.score_stage(score.load_stage(tmp_path / "stage"))
    assert scored["questions"]["dev-4"]["diagnostics"]["unanswered"] == 1


def test_an_interrupted_stage_keeps_its_samples_and_resumes_the_rest(stub, demo, tmp_path, monkeypatch, capsys):
    real, calls = rollout.rollout, []

    async def interrupted_on_third(*args, **kwargs):
        calls.append(1)
        if len(calls) == 3:
            raise KeyboardInterrupt
        return await real(*args, **kwargs)

    monkeypatch.setattr(rollout, "rollout", interrupted_on_third)
    assert run_rollouts(stub, demo, tmp_path, "--questions", "dev-1,dev-4", "--samples", "2") == 130
    folder = tmp_path / "stage"
    info = common.read_stage(folder)
    assert info["stopped"] == "interrupted" and "finished" not in info and "seconds" in info
    assert [(s["question"], s["sample"]) for s in samples_of(folder)] == [("dev-1", 1), ("dev-4", 1)]
    assert "--resume" in capsys.readouterr().err
    assert "unfinished (interrupted)" in score.report(score.score_stage(score.load_stage(folder)), info)

    monkeypatch.setattr(rollout, "rollout", real)
    with (folder / "samples.jsonl").open("a") as out:
        out.write('{"question": "dev-1", "sam')  # a sample cut off by a kill
    StubOllama.seen = []
    assert rollout.main(["stage", "--resume", "--db", demo, "--ollama-url", stub, "--stages-dir", str(tmp_path)]) == 0
    assert len(StubOllama.seen) == 2
    assert [(s["question"], s["sample"]) for s in samples_of(folder)] == [
        ("dev-1", 1), ("dev-4", 1), ("dev-1", 2), ("dev-4", 2)]
    info = common.read_stage(folder)
    assert "finished" in info and "stopped" not in info and len(info["resumed"]) == 1
    assert info["questions"] == ["dev-1", "dev-4"] and info["samples"] == 2
    assert "resuming: 2 recorded, 2 left to run" in capsys.readouterr().out


def test_resuming_refuses_what_would_mix_two_runs(stub, demo, tmp_path, monkeypatch, capsys):
    def resume(*extra):
        StubOllama.seen = []
        with pytest.raises(SystemExit) as raised:
            rollout.main(["stage", "--resume", "--db", demo, "--ollama-url", stub, "--stages-dir", str(tmp_path),
                          *extra])
        assert raised.value.code == 2 and StubOllama.seen == []
        return capsys.readouterr().err

    assert "no stage to resume" in resume()
    assert run_rollouts(stub, demo, tmp_path, "--questions", "dev-1", "--samples", "1") == 0
    assert "already finished" in resume()
    info = common.read_stage(tmp_path / "stage")
    common.write_stage(tmp_path / "stage", {k: v for k, v in info.items() if k != "finished"})
    assert "leave out --samples" in resume("--samples", "3")
    monkeypatch.setattr(common, "code_hash", lambda: "0" * 64)
    assert "changed since stage started" in resume()
    monkeypatch.undo()
    monkeypatch.setitem(mcp_server.DESCRIPTIONS, "search_postings", "Changed for a test.")
    assert "tools as sent differ" in resume()
    monkeypatch.undo()
    common.write_stage(tmp_path / "stage", {**info, "finished": None, "ollama_version": "0.0-other"})
    assert "Ollama 0.0-other" in resume()


def test_a_dry_run_states_the_rollouts_and_sends_nothing(stub, demo, tmp_path, capsys):
    assert run_rollouts(stub, demo, tmp_path, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "5 questions" in out and "10 samples = 50 rollouts" in out and "one code version" in out
    assert StubOllama.seen == [] and not (tmp_path / "stage").exists()


def test_a_single_step_stage_records_first_calls_and_scores_first_call_checks(stub, demo, tmp_path):
    StubOllama.script = lambda body: reply(calls=[("jobhunt_search_postings", {"workplace": "Remote"})])
    assert run_rollouts(stub, demo, tmp_path, "--first-step", "--samples", "2", "--questions", "dev-1,dev-2") == 0
    assert len(StubOllama.seen) == 4
    assert all(len(s["exchanges"]) == 1 and s["answered"] is None for s in samples_of(tmp_path / "stage"))
    scored = score.score_stage(score.load_stage(tmp_path / "stage"))
    assert scored["kind"] == "first-step"
    assert {qid: (q["passed"], list(q["checks"])) for qid, q in scored["questions"].items()} == {
        "dev-1": (2, ["first_call:search_postings"]), "dev-2": (0, ["first_call:search_postings"])}
    assert scored["questions"]["dev-2"]["diagnostics"]["carried_filter"] == 2
    assert "unanswered" not in scored["questions"]["dev-2"]["diagnostics"]


@pytest.mark.parametrize("context, runs", [(4096, False), (8192, True)])
def test_the_context_is_checked_after_the_first_request(stub, demo, tmp_path, context, runs, capsys):
    StubOllama.context = context
    if runs:
        assert run_rollouts(stub, demo, tmp_path, "--samples", "2", "--questions", "dev-4") == 0
        assert len(StubOllama.seen) == 2
    else:
        exits_2(run_rollouts, stub, demo, tmp_path, "--samples", "2", "--questions", "dev-4")
        assert len(StubOllama.seen) == 1 and "OLLAMA_CONTEXT_LENGTH" in capsys.readouterr().err
        assert common.read_stage(tmp_path / "stage")["stopped"] == "context below 8192"


# --- the fidelity check (4.4) ---


def test_the_check_finds_a_real_capture_equal(demo, capsys):
    assert rollout.main(["--check", str(FIXTURE), "--db", demo]) == 0
    assert capsys.readouterr().out.strip().endswith("14 of 14 requests equal")


def test_the_check_reports_a_changed_description(demo, capsys, monkeypatch):
    monkeypatch.setitem(mcp_server.DESCRIPTIONS, "posting_fit", "Changed for a test.")
    assert rollout.main(["--check", str(FIXTURE), "--db", demo]) == 1
    out = capsys.readouterr().out
    assert "tools[2].function.description: differs at character 10" in out and "0 of 14 requests equal" in out


# --- session batches (5.1) ---


def test_a_batch_dry_run_states_the_sessions(demo, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(batch.subprocess, "Popen", lambda *a, **k: pytest.fail("nothing may start"))
    assert batch.main(["stage", "--runs", "3", "--db", demo, "--dry-run", "--stages-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "3 ollmcp 0.35.1 sessions of the dev set with qwen3:8b" in out and "5 questions a session" in out
    assert "capture proxy on 127.0.0.1:11436" in out and not (tmp_path / "stage").exists()


def test_a_batch_refuses_a_non_demo_database_before_starting_anything(tmp_path, monkeypatch):
    monkeypatch.setattr(batch.subprocess, "Popen", lambda *a, **k: pytest.fail("nothing may start"))
    engine = make_engine(f"sqlite:///{tmp_path / 'own.db'}")
    init_db(engine)
    engine.dispose()
    exits_2(batch.main, ["stage", "--runs", "1", "--db", f"sqlite:///{tmp_path / 'own.db'}",
                         "--stages-dir", str(tmp_path)])
    exits_2(batch.main, ["stage", "--runs", "1", "--listen", "0.0.0.0:11436", "--stages-dir", str(tmp_path)])
    assert not (tmp_path / "stage").exists()


def test_the_batch_starts_the_client_as_docs_mcp_says(demo):
    command = batch.client_command("127.0.0.1:11436", MODEL, Path("/x/jobhunt-demo.json"))
    assert command[1:] == ["--provider", "ollama", "--host", "http://127.0.0.1:11436", "--model", MODEL,
                           "--servers-json", "/x/jobhunt-demo.json"]
    server = batch.servers_json(demo)["mcpServers"]["jobhunt"]
    assert server["args"] == ["mcp", "--db", demo, "--share", "postings,profile"]


# --- history conditions and orders (add-mcp-eval-history) ---

DEV_QUESTIONS = common.load_set("dev")["questions"]
DEV_IDS = [q["id"] for q in DEV_QUESTIONS]
BY_TEXT = {q["text"]: q["id"] for q in DEV_QUESTIONS}


def last_question(body) -> str:
    return BY_TEXT[next(m["content"] for m in reversed(body["messages"]) if m["role"] == "user")]


def first_requests(seen) -> dict[str, list]:
    """Each question's first requests (those whose last message is the question), in order."""
    out: dict[str, list] = {}
    for body in seen:
        if body["messages"][-1]["role"] == "user":
            out.setdefault(last_question(body), []).append(body)
    return out


def test_an_old_stage_reads_as_fixed_in_the_sets_order_and_sessions_as_own():
    old = {"kind": "rollout", "set": "dev", "model": MODEL}
    assert common.conditions(old) == {"history": "fixed", "order": "set", "orders": None}
    assert common.conditions({**old, "kind": "first-step"})["history"] == "fixed"
    assert common.conditions({**old, "kind": "session"})["history"] == "own"
    assert common.condition_label(old) == "history fixed, order set"


def test_a_batch_records_its_sessions_as_own(stub, demo, tmp_path, monkeypatch):
    monkeypatch.setattr(common, "OLLMCP", Path(sys.executable))
    monkeypatch.setattr(batch, "run_session", lambda *args: 0)
    assert batch.main(["stage", "--runs", "1", "--db", demo, "--ollama-url", stub, "--stages-dir", str(tmp_path)]) == 0
    info = common.read_stage(tmp_path / "stage")
    assert (info["kind"], info["history"], info["order"]) == ("session", "own", "set")


@pytest.mark.parametrize("n, rows, each", [(5, 10, 2), (4, 4, 1)])
def test_williams_rows_balance_positions_and_neighbours(n, rows, each):
    ids = [f"q{i}" for i in range(n)]
    orders = common.williams(ids)
    assert len(orders) == rows and all(sorted(row) == ids for row in orders)
    for position in range(n):
        assert {qid: sum(row[position] == qid for row in orders) for qid in ids} == dict.fromkeys(ids, each)
    pairs = [(row[j], row[j + 1]) for row in orders for j in range(n - 1)]
    assert {(a, b): pairs.count((a, b)) for a in ids for b in ids if a != b} == {
        (a, b): each for a in ids for b in ids if a != b}


def test_history_in_a_given_order_is_the_questions_before_it_in_that_order():
    order = ["dev-3", "dev-5", "dev-2", "dev-1", "dev-4"]
    messages = common.history(DEV_QUESTIONS, DEV_IDS.index("dev-2"), order)
    assert [m["content"] for m in messages if m["role"] == "user"] == [
        DEV_QUESTIONS[2]["text"], DEV_QUESTIONS[4]["text"]]
    assert common.history(DEV_QUESTIONS, DEV_IDS.index("dev-3"), order) == []
    assert common.history(DEV_QUESTIONS, 2) == common.history(DEV_QUESTIONS, 2, DEV_IDS)


@pytest.mark.parametrize("extra, message", [
    (["--history", "none", "--order", "balanced"], "needs a history"),
    (["--history", "own", "--questions", "dev-2"], "whole set"),
    (["--history", "own", "--first-step"], "single steps"),
])
def test_conditions_that_cant_run_are_refused_before_sending(stub, demo, tmp_path, capsys, extra, message):
    exits_2(run_rollouts, stub, demo, tmp_path, *extra)
    assert message in capsys.readouterr().err
    assert StubOllama.seen == [] and not (tmp_path / "stage").exists()


def test_a_dry_run_names_the_conditions_and_an_unbalanced_count(stub, demo, tmp_path, capsys):
    assert run_rollouts(stub, demo, tmp_path, "--dry-run", "--history", "none") == 0
    out = capsys.readouterr().out
    assert "history: none (each question alone)" in out and "order: the set's" in out
    assert run_rollouts(stub, demo, tmp_path, "--dry-run", "--order", "balanced", "--samples", "7") == 0
    out = capsys.readouterr().out
    assert "history: fixed" in out and "balanced, 10 orders" in out and "the stage isn't balanced" in out
    assert run_rollouts(stub, demo, tmp_path, "--dry-run", "--history", "own", "--samples", "2") == 0
    assert "5 questions" in (out := capsys.readouterr().out) and "2 chains" in out and "history: own" in out
    assert StubOllama.seen == [] and not (tmp_path / "stage").exists()


@pytest.mark.parametrize("first_step", [False, True])
def test_without_history_every_request_starts_with_the_question(stub, demo, tmp_path, first_step):
    StubOllama.script = lambda body: (reply("The answer.") if body["messages"][-1]["role"] == "tool"
                                      else reply(calls=[("jobhunt_profile_skills", {})]))
    extra = ["--first-step"] if first_step else []
    assert run_rollouts(stub, demo, tmp_path, "--history", "none", "--samples", "1", *extra) == 0
    assert len(StubOllama.seen) == (5 if first_step else 10)
    for body in StubOllama.seen:
        assert body["messages"][0]["role"] == "user" and body["messages"][0]["content"] in BY_TEXT
        assert [m["role"] for m in body["messages"]].count("user") == 1
    assert {q: len(b) for q, b in first_requests(StubOllama.seen).items()} == dict.fromkeys(DEV_IDS, 1)
    info = common.read_stage(tmp_path / "stage")
    assert (info["history"], info["order"]) == ("none", "set") and "orders" not in info


def test_a_balanced_stage_asks_each_sample_after_its_rows_questions(stub, demo, tmp_path):
    assert run_rollouts(stub, demo, tmp_path, "--order", "balanced", "--questions", "dev-2") == 0
    info = common.read_stage(tmp_path / "stage")
    assert info["order"] == "balanced" and info["orders"] == common.williams(DEV_IDS)
    samples = samples_of(tmp_path / "stage")
    assert [s["row"] for s in samples] == list(range(1, 11))
    i = DEV_IDS.index("dev-2")
    for sample, body in zip(samples, StubOllama.seen, strict=True):
        row = info["orders"][sample["row"] - 1]
        assert body["messages"] == common.history(DEV_QUESTIONS, i, row) + [
            {"role": "user", "content": DEV_QUESTIONS[i]["text"]}]
    positions = [info["orders"][s["row"] - 1].index("dev-2") for s in samples]
    assert sorted(positions) == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4]


def answers_by_question(stuck=()):
    """A stub script: each question answered with its own text, or tools called for ever for those in `stuck`."""
    def script(body):
        qid = last_question(body)
        return reply(calls=[("jobhunt_profile_skills", {})]) if qid in stuck else reply(f"Answer to {qid}.")
    return script


def test_own_chains_keep_the_models_answers_and_leave_out_a_stopped_question(stub, demo, tmp_path):
    StubOllama.script = answers_by_question(stuck={"dev-2"})
    assert run_rollouts(stub, demo, tmp_path, "--history", "own", "--samples", "2") == 0
    firsts = first_requests(StubOllama.seen)
    for k in range(2):
        assert firsts["dev-1"][k]["messages"] == [{"role": "user", "content": DEV_QUESTIONS[0]["text"]}]
        assert firsts["dev-3"][k]["messages"][:-1] == common.history_messages(
            [(DEV_QUESTIONS[0]["text"], "Answer to dev-1.")])  # dev-2 stopped at the loop limit: left out
        assert firsts["dev-4"][k]["messages"][1] == {"role": "assistant", "content": "Answer to dev-1."}
        assert firsts["dev-4"][k]["messages"][3] == {"role": "assistant", "content": "Answer to dev-3."}
    samples = samples_of(tmp_path / "stage")
    assert [(s["question"], s["chain"], s["position"]) for s in samples] == [
        (qid, k, p) for k in (1, 2) for p, qid in enumerate(DEV_IDS, start=1)]
    scored = score.score_stage(score.load_stage(tmp_path / "stage"))
    assert scored["history"] == "own"
    report = score.report(scored, common.read_stage(tmp_path / "stage"))
    assert "history own, order set" in report and "paired by chain" in report


def test_an_own_stage_resumes_a_chain_with_its_recorded_answers(stub, demo, tmp_path, monkeypatch, capsys):
    StubOllama.script = answers_by_question()
    real, calls = rollout.rollout, []

    async def interrupted_on_second(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return await real(*args, **kwargs)

    monkeypatch.setattr(rollout, "rollout", interrupted_on_second)
    assert run_rollouts(stub, demo, tmp_path, "--history", "own", "--samples", "1") == 130
    assert [s["question"] for s in samples_of(tmp_path / "stage")] == ["dev-1"]
    monkeypatch.setattr(rollout, "rollout", real)

    def resume(*extra):
        return rollout.main(["stage", "--resume", "--db", demo, "--ollama-url", stub, "--stages-dir", str(tmp_path),
                             *extra])

    for option in (["--history", "none"], ["--order", "balanced"]):
        StubOllama.seen = []
        exits_2(resume, *option)
        assert "leave out " + option[0] in capsys.readouterr().err and StubOllama.seen == []
    assert resume() == 0
    assert StubOllama.seen[0]["messages"] == common.history_messages(
        [(DEV_QUESTIONS[0]["text"], "Answer to dev-1.")]) + [{"role": "user", "content": DEV_QUESTIONS[1]["text"]}]
    assert [s["question"] for s in samples_of(tmp_path / "stage")] == DEV_IDS
    assert common.read_stage(tmp_path / "stage")["history"] == "own"


def write_rollout_stage(folder: Path, info: dict, samples: list[dict]):
    folder.mkdir(parents=True)
    common.write_stage(folder, {"set": "dev", "model": MODEL, "tools": [], "companies": [], **info})
    (folder / "samples.jsonl").write_text("".join(json.dumps(s) + "\n" for s in samples))


def searched(question, arguments, k=1, **extra):
    request = {"model": MODEL, "messages": [{"role": "user", "content": question["text"]}]}
    exchanges = [{"request": request, "reply": {"content": "", "tool_calls": [
        {"function": {"name": "jobhunt_search_postings", "arguments": arguments}}]}}]
    return {"question": question["id"], "sample": k, "answered": None, "exchanges": exchanges, **extra}


def test_a_stage_without_history_counts_an_unasked_filter(tmp_path):
    dev2 = DEV_QUESTIONS[1]
    for history, name, other in (("none", "unasked_filter", "carried_filter"),
                                 ("fixed", "carried_filter", "unasked_filter")):
        folder = tmp_path / history
        write_rollout_stage(folder, {"kind": "first-step", "history": history, "order": "set", "finished": "x"},
                            [searched(dev2, {"q": "x", "workplace": "Remote"})])
        scored = score.score_stage(score.load_stage(folder))
        diagnostics = scored["questions"]["dev-2"]["diagnostics"]
        assert diagnostics[name] == 1 and other not in diagnostics
        assert f"history {history}, order set" in score.report(scored, common.read_stage(folder))


def test_an_unfinished_balanced_stage_is_flagged(tmp_path):
    orders = common.williams(DEV_IDS)
    folder = tmp_path / "balanced"
    write_rollout_stage(folder, {"kind": "first-step", "history": "fixed", "order": "balanced", "orders": orders,
                                 "samples": 10, "questions": ["dev-2"], "stopped": "interrupted"},
                        [searched(DEV_QUESTIONS[1], {"q": "x"}, row=1)])
    text = score.report(score.score_stage(score.load_stage(folder)), common.read_stage(folder))
    assert "order balanced (10 orders)" in text and "balanced order is incomplete" in text


def test_detail_shows_a_chains_earlier_questions(tmp_path, capsys):
    dev1, dev2 = DEV_QUESTIONS[:2]
    sample = searched(dev2, {"q": "x"}, chain=1, position=2)
    sample["exchanges"][0]["request"]["messages"] = common.history_messages([(dev1["text"], "Mine.")]) + [
        {"role": "user", "content": dev2["text"]}]
    write_rollout_stage(tmp_path / "own", {"kind": "rollout", "history": "own", "order": "set"}, [sample])
    assert detail.main([str(tmp_path / "own"), "dev-2"]) == 0
    out = capsys.readouterr().out
    assert "history own, order set (chain 1, position 2); asked after: dev-1" in out


def test_an_own_held_out_chain_stays_unread(tmp_path, question_copies, capsys):
    holdout = common.load_set("holdout")["questions"]
    request = {"model": MODEL, "messages": common.history_messages([(holdout[0]["text"], "SECRET EARLIER")]) + [
        {"role": "user", "content": holdout[1]["text"]}]}
    sample = {"question": holdout[1]["id"], "sample": 1, "chain": 1, "position": 2, "answered": True,
              "exchanges": [{"request": request, "reply": {"content": "SECRET ANSWER", "tool_calls": []}}]}
    folder = tmp_path / "held-own"
    folder.mkdir()
    common.write_stage(folder, {"kind": "rollout", "set": "holdout", "model": MODEL, "history": "own", "tools": []})
    (folder / "samples.jsonl").write_text(json.dumps(sample) + "\n")
    exits_2(detail.main, [str(folder), holdout[1]["id"], "--questions-dir", str(question_copies)])
    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err


def condition_stage(name, passes, history="fixed", order="set"):
    return {**scored_stage(name, passes), "history": history, "order": order}


def test_code_versions_are_compared_under_one_condition_only():
    base = {"set": "dev", "kind": "rollout", "model": MODEL}
    assert "history conditions" in compare.refusal(base, {**base, "history": "none"})
    assert "orders" in compare.refusal({**base, "history": "fixed"}, {**base, "order": "balanced"})
    assert compare.refusal(base, {**base, "history": "fixed", "order": "set"}) is None
    result = compare.compare(condition_stage("a", {"dev-2": 2}), condition_stage("b", {"dev-2": 9}))
    assert "history fixed, order set" in compare.report(result, [])


def test_conditions_are_compared_on_one_code_version_only():
    base = {"set": "dev", "kind": "rollout", "model": MODEL, "code_sha256": "x"}
    assert compare.conditions_refusal(base, {**base, "history": "none"}) is None
    assert compare.conditions_refusal(base, {**base, "order": "balanced"}) is None
    assert "different code" in compare.conditions_refusal(base, {**base, "history": "none", "code_sha256": "y"})
    assert "both stages ran" in compare.conditions_refusal(base, {**base, "history": "fixed"})
    for key, other in (("set", "holdout"), ("kind", "first-step"), ("model", "qwen3:14b")):
        assert compare.conditions_refusal(base, {**base, "history": "none", key: other})


def test_a_history_effect_is_more_fewer_or_within_noise():
    result = compare.compare_conditions(condition_stage("fixed", {"dev-1": 9, "dev-2": 2, "dev-3": 6}),
                                        condition_stage("none", {"dev-1": 2, "dev-2": 9, "dev-3": 8}, history="none"))
    assert {qid: row["verdict"] for qid, row in result["questions"].items()} == {
        "dev-1": "fewer", "dev-2": "more", "dev-3": "within noise"}
    assert "verdict" not in result
    text = compare.conditions_report(result, [])
    assert "history none against fixed" in text and "p(more)" in text and "p(fewer)" in text
    assert "set:" not in text


def test_compare_conditions_refuses_different_code_from_the_command_line(tmp_path, capsys):
    for name, code in (("a", "x"), ("b", "y")):
        write_rollout_stage(tmp_path / name, {"kind": "first-step", "history": "fixed" if name == "a" else "none",
                                              "code_sha256": code, "finished": "x"},
                            [searched(DEV_QUESTIONS[1], {"q": "x"})])
    exits_2(compare.main, ["--conditions", str(tmp_path / "a"), str(tmp_path / "b")])
    assert "different code" in capsys.readouterr().err
    exits_2(compare.main, [str(tmp_path / "a"), str(tmp_path / "b")])
    assert "history conditions" in capsys.readouterr().err
