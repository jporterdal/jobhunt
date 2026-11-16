"""Shared ground for the MCP measurement scripts (docs/mcp-eval.md): the data folder, the guards, the question sets,
the Ollama calls and the documented client's rendering of tools, results and messages.

The scripts measure how a model uses jobhunt's MCP server on the demo database only. Every command opens its database
read-only and refuses one that `jobhunt demo` didn't build, talks only to loopback addresses, and runs no model
unless a person starts it. Not part of the jobhunt package; nothing in `src/jobhunt/` imports this.

The rendering is ollmcp 0.35.1's (the client docs/mcp.md documents), read from its source and checked against real
captures (`rollout.py --check`):

- each tool listed by the server is sent as `{"type": "function", "function": {"name": "jobhunt_<tool>",
  "description": "[jobhunt] <description>", "parameters": <input schema>}}`, in the server's order, the schema cut
  down to the fields the `ollama` package's `Tool` model keeps (`ollama_parameters`);
- a request is `{model, stream, options: {}, think: "medium", messages, tools}`;
- a new question's messages are the earlier questions (`user`) with their final answers (`assistant`, left out when
  empty; a question stopped at the loop limit isn't kept), then the question;
- within a question, each reply is appended as `{"role": "assistant", "content": ..., "tool_calls": [...]}`, the
  content left out when empty and each call as `{"function": {"name", "arguments"}}`; then one
  `{"role": "tool", "content": ..., "tool_name": <name as called>}` per call, whose content is the result's text
  blocks joined by a blank line (the structured content as compact JSON when there's no text block). An error
  result is passed the same way (its text is the server's "Error executing tool ..."); a call to a name the client
  doesn't know gets no tool message at all (ollmcp only prints an error);
- after 7 rounds of tool calls (`LOOP_LIMIT`) the client stops and asks the user what to do.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))  # scripts/, for ollama_capture

from ollama_capture import is_loopback  # noqa: E402

DATA = REPO / "data" / "mcp-eval"
DEMO_DIR = DATA / "demo"
DEMO_DB = DEMO_DIR / "jobhunt.db"
STAGES = DATA / "stages"
OLLMCP = DATA / "ollmcp-venv" / "bin" / "ollmcp"
QUESTIONS = HERE / "questions"
SETS = ("dev", "holdout")
CODE_FILES = (REPO / "src" / "jobhunt" / "mcp_server.py", REPO / "src" / "jobhunt" / "mcp_tools.py")

DEFAULT_MODEL = "qwen3:8b"
DEFAULT_OLLAMA = "http://127.0.0.1:11434"
SCOPES = ("postings", "profile")
SERVER = "jobhunt"  # the server's name in the client's configuration, and so the prefix of every tool name
LOOP_LIMIT = 7  # ollmcp's loop_limit
THINK = "medium"  # what ollmcp sends for a thinking model with its default reasoning effort
MIN_CONTEXT = 8192  # question 5 of the dev set overflowed 4096
OLLMCP_VERSION = "0.35.1"

CHECK_KINDS = ("answer_urls", "answer_figures", "answer_mentions", "answer_amounts", "called", "first_call")
FILTERS = ("tag", "min_interest", "unrated", "workplace", "status", "dismissed")


def fail(message: str) -> NoReturn:
    """Print the refusal and exit with status 2 (before anything is sent)."""
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(2)


# --- guards ---


def default_db_url() -> str:
    return f"sqlite:///{DEMO_DB}"


def ensure_demo(url: str) -> None:
    """Build the default demo database with `jobhunt demo` when it's missing (only the default; another address is
    used as given)."""
    if url != default_db_url() or DEMO_DB.exists():
        return
    jobhunt = Path(sys.executable).parent / "jobhunt"
    print(f"building the demo database in {DEMO_DIR} (jobhunt demo)", file=sys.stderr)
    command = [str(jobhunt), "demo", "--db", url, "--documents", str(DEMO_DIR / "documents")]
    if subprocess.run(command, stdout=subprocess.DEVNULL).returncode != 0:
        fail("`jobhunt demo` failed")


def open_demo(url: str):
    """A read-only engine on the demo database at `url`; refuses (exit 2) a missing database, one not at the
    current schema version, and any database not built by `jobhunt demo` (no `demo.created_at` setting)."""
    from sqlalchemy.exc import SQLAlchemyError

    from jobhunt import migrate, userdata
    from jobhunt.db import MissingDatabase, read_only_engine

    try:
        engine = read_only_engine(url)
    except MissingDatabase as exc:
        fail(f"{exc}; the measurements run on the demo database (build one with `jobhunt demo`)")
    try:
        if migrate.current_revision(engine) != migrate.head_revision():
            engine.dispose()
            fail("the database isn't at the current schema version; rebuild the demo with `jobhunt demo`")
        with engine.connect() as conn:
            marked = userdata.get_setting(conn, "demo.created_at")
    except SQLAlchemyError as exc:
        engine.dispose()
        fail(f"cannot read the database: {exc}")
    if marked is None:
        engine.dispose()
        fail("this database wasn't built by `jobhunt demo`; the MCP measurements run on the demo only, never on "
             "your own data")
    return engine


def demo_companies(engine) -> list[str]:
    """Every company of the demo's postings, dismissed ones included (for the combined-`q` diagnostic)."""
    from jobhunt import mcp_tools

    with engine.connect() as conn:
        result = mcp_tools.TOOLS["search_postings"](conn, dismissed="included", limit=mcp_tools.SEARCH_LIMIT_MAX)
    return sorted({posting["company"] for posting in result["postings"] if posting.get("company")})


def ollama_base(url: str) -> str:
    """The Ollama address without a trailing slash; refuses (exit 2) anything but an http:// loopback address."""
    parts = urlsplit(url)
    if parts.scheme != "http" or not parts.hostname:
        fail(f"the Ollama address must be an http:// address, got {url!r}")
    if not is_loopback(parts.hostname):
        fail(f"the Ollama address must be a loopback address (localhost, 127.0.0.0/8, ::1), got {parts.hostname!r}")
    return url.rstrip("/")


# --- Ollama ---

# No proxy from the environment: the guard checked the address the request goes to.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Ollama:
    """The few Ollama calls the scripts make, to a checked loopback address."""

    def __init__(self, base: str, timeout: float = 1800):
        self.base = ollama_base(base)
        self.timeout = timeout

    def _send(self, path: str, body: dict | None = None) -> Any:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, headers={"Content-Type": "application/json"})
        with _OPENER.open(request, timeout=self.timeout) as response:
            return json.loads(response.read())

    def version(self) -> str | None:
        try:
            return self._send("/api/version").get("version")
        except (OSError, ValueError):
            return None

    def chat(self, body: dict) -> dict:
        return self._send("/api/chat", body)

    def context_length(self, model: str) -> int | None:
        """The loaded model's context size from `/api/ps`, None when it isn't loaded or not reported."""
        for entry in self._send("/api/ps").get("models") or []:
            if model in (entry.get("name"), entry.get("model")):
                return entry.get("context_length")
        return None


def check_context(ollama: Ollama, model: str) -> None:
    """Stop (exit 2) when the loaded model's context is below MIN_CONTEXT: the client sends no context size, so the
    server's own is used, and a smaller one cuts long questions off."""
    try:
        size = ollama.context_length(model)
    except (OSError, ValueError) as exc:
        fail(f"cannot read /api/ps: {exc}")
    if size is not None and size < MIN_CONTEXT:
        fail(f"{model} is loaded with a context of {size} tokens, below {MIN_CONTEXT}; start Ollama with "
             f"OLLAMA_CONTEXT_LENGTH={MIN_CONTEXT} (docs/mcp-eval.md) and run again")


def assembled(reply: dict) -> dict:
    """A non-streamed /api/chat reply in the capture proxy's `assembled` form: content, thinking and tool calls, and
    the reply's counts and durations."""
    message = reply.get("message") or {}
    out = {"content": message.get("content") or "", "thinking": message.get("thinking") or "",
           "tool_calls": message.get("tool_calls") or []}
    out.update({k: v for k, v in reply.items() if k != "message"})
    return out


# --- question sets ---


def set_path(name: str) -> Path:
    if name not in SETS:
        fail(f"unknown question set {name!r} (one of: {', '.join(SETS)})")
    return QUESTIONS / f"{name}.json"


def load_set(name: str, path: Path | None = None) -> dict:
    """A question set: `{"set": name, "questions": [...]}`, checked for its fields and check kinds."""
    path = path or set_path(name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail(f"cannot read the question set {path}: {exc}")
    if data.get("set") != name:
        fail(f"{path} holds the set {data.get('set')!r}, not {name!r}")
    seen = set()
    for question in data.get("questions") or []:
        missing = {"id", "text", "history_answer", "checks", "unasked_filters", "sources"} - set(question)
        if missing:
            fail(f"{path}: question {question.get('id')!r} has no {', '.join(sorted(missing))}")
        if question["id"] in seen:
            fail(f"{path}: question id {question['id']!r} appears twice")
        seen.add(question["id"])
        for check in question["checks"]:
            if check.get("kind") not in CHECK_KINDS:
                fail(f"{path}: question {question['id']}: unknown check {check.get('kind')!r}")
        unknown = set(question["unasked_filters"]) - set(FILTERS)
        if unknown:
            fail(f"{path}: question {question['id']}: unknown filters {', '.join(sorted(unknown))}")
    return data


def _line(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def dump_set(data: dict) -> str:
    """A question set in the files' layout: one field a line, each check on a line of its own, so a moved question
    shows in git as lines moved."""
    lines = ["{"]
    head = [f" {_line(key)}: {_line(value)}" for key, value in data.items() if key != "questions"]
    lines += [line + "," for line in head]
    lines.append(' "questions": [')
    for i, question in enumerate(data["questions"]):
        fields = []
        for key, value in question.items():
            if key == "checks":
                checks = ",\n".join(f"    {_line(check)}" for check in value)
                fields.append(f'   "checks": [\n{checks}\n   ]')
            else:
                fields.append(f"   {_line(key)}: {_line(value)}")
        comma = "," if i < len(data["questions"]) - 1 else ""
        lines.append("  {\n" + ",\n".join(fields) + "\n  }" + comma)
    lines += [" ]", "}"]
    return "\n".join(lines) + "\n"


def history(questions: list[dict], index: int) -> list[dict]:
    """The messages before question `index`: each earlier question and its recorded final answer, as ollmcp keeps
    them."""
    messages = []
    for question in questions[:index]:
        messages.append({"role": "user", "content": question["text"]})
        if question["history_answer"]:
            messages.append({"role": "assistant", "content": question["history_answer"]})
    return messages


# --- the client's rendering ---


def wire_name(tool: str) -> str:
    """The name the client sends for a server's tool: `<server>.<tool>` with the dot (which providers reject)
    replaced."""
    return f"{SERVER}_{tool}"


PROPERTY_FIELDS = ("type", "items", "description", "enum")


def ollama_parameters(schema: dict) -> dict:
    """An input schema as the `ollama` package's `Tool` model (0.6.3, under ollmcp's provider layer) sends it: the
    object's `type`, `$defs`, `items` and `required`, and for each property only its `type`, `items`, `description`
    and `enum`, values that are None left out. So titles, defaults, ranges, `additionalProperties` and a nullable
    property's `anyOf` (and with it its type) never reach the model."""
    out: dict[str, Any] = {"type": "object"}
    for key in ("$defs", "items", "required"):
        if schema.get(key) is not None:
            out[key] = schema[key]
    if schema.get("properties") is not None:
        out["properties"] = {
            name: {field: prop[field] for field in PROPERTY_FIELDS if prop.get(field) is not None}
            for name, prop in schema["properties"].items()
        }
    return out


def render_tools(tools) -> list[dict]:
    """Listed MCP tools (`Tool` objects, in the server's order) as the client sends them."""
    return [
        {"type": "function", "function": {
            "name": wire_name(tool.name),
            "description": f"[{SERVER}] {tool.description}",
            "parameters": ollama_parameters(tool.input_schema),
        }}
        for tool in tools
    ]


def render_result(result) -> str:
    """A `CallToolResult` as the client passes it to the model: the text blocks joined by a blank line, else the
    structured content as compact JSON, else the client's placeholder."""
    parts = [str(item.text) for item in result.content if getattr(item, "type", None) == "text"]
    if not parts and result.structured_content is not None:
        parts.append(json.dumps(result.structured_content, separators=(",", ":"), ensure_ascii=False, default=str))
    return "\n\n".join(parts) if parts else "Tool executed successfully (no text content returned)"


def assistant_message(reply: dict) -> dict:
    """A reply (assembled) appended to the messages, as the client's provider layer writes it for Ollama."""
    message: dict[str, Any] = {"role": "assistant"}
    if reply.get("content"):
        message["content"] = reply["content"]
    calls = reply.get("tool_calls") or []
    if calls:
        message["tool_calls"] = [
            {"function": {"name": call["function"]["name"], "arguments": call_arguments(call)}} for call in calls
        ]
    return message


def call_arguments(call: dict) -> dict:
    arguments = call["function"].get("arguments")
    if isinstance(arguments, str):
        return json.loads(arguments) if arguments else {}
    return arguments or {}


def tool_message(name: str, content: str) -> dict:
    return {"role": "tool", "content": content, "tool_name": name}


@contextlib.asynccontextmanager
async def connect(engine) -> AsyncIterator[Server]:
    """The working tree's MCP server for the demo, through the SDK's in-memory client."""
    from mcp import Client

    from jobhunt import mcp_server

    async with Client(mcp_server.build(engine, SCOPES)) as client:
        yield Server(client, (await client.list_tools()).tools)


class Server:
    """An in-memory connection to the server, with its tools rendered and calls answered as the client answers
    them."""

    def __init__(self, client, tools):
        self.client = client
        self.listed = list(tools)
        self.tools = render_tools(self.listed)
        self.qualified = {wire_name(tool.name): f"{SERVER}.{tool.name}" for tool in self.listed}

    async def answer(self, call: dict) -> str | None:
        """The tool message content for one call, or None when the client wouldn't call anything (a name it doesn't
        map to a server)."""
        name = call["function"]["name"]
        qualified = self.qualified.get(name, name)
        server, dot, tool = qualified.partition(".")
        if not dot or server != SERVER:
            return None
        try:
            result = await self.client.call_tool(tool, call_arguments(call))
        except Exception as exc:  # noqa: BLE001 (the client passes any failure on as text)
            return f"Error calling tool {qualified}: {exc}"
        return render_result(result)


def run_async(function, *args):
    """anyio.run, with a SystemExit or KeyboardInterrupt raised inside the client's task group raised as itself
    (the task group wraps it in an exception group)."""
    import anyio

    try:
        return anyio.run(function, *args)
    except BaseExceptionGroup as group:
        for kind in (SystemExit, KeyboardInterrupt):
            found = group.subgroup(kind)
            while isinstance(found, BaseExceptionGroup):
                found = found.exceptions[0]
            if found is not None:
                raise found from None
        raise


def request_body(model: str, messages: list[dict], tools: list[dict], stream: bool = False) -> dict:
    return {"model": model, "stream": stream, "options": {}, "think": THINK, "messages": messages, "tools": tools}


# --- stages ---


def code_hash() -> str:
    digest = hashlib.sha256()
    for path in CODE_FILES:
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def git_commit() -> str | None:
    try:
        head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "src"], capture_output=True,
                               text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return head + ("+changes" if dirty else "")


def set_hash(questions: list[dict]) -> str:
    """A hash of what a set puts into requests (ids, texts and history answers, in order); checks aren't in it, so
    editing a check doesn't change it."""
    shown = [[question["id"], question["text"], question["history_answer"]] for question in questions]
    return hashlib.sha256(json.dumps(shown, ensure_ascii=False).encode()).hexdigest()


def stage_folder(name: str, root: Path | None = None) -> Path:
    if not name or "/" in name or name.startswith("."):
        fail(f"a stage name is one folder name, got {name!r}")
    return (root or STAGES) / name


def new_stage(name: str, root: Path | None = None) -> Path:
    """The folder for a new stage; refuses a name already used, so two runs never mix."""
    folder = stage_folder(name, root)
    if folder.exists():
        fail(f"the stage {folder} already exists; choose another name (or continue a stopped rollout stage with "
             "--resume)")
    folder.mkdir(parents=True)
    code = folder / "code"
    code.mkdir()
    for path in CODE_FILES:
        shutil.copy2(path, code / path.name)
    return folder


def write_stage(folder: Path, info: dict) -> None:
    (folder / "stage.json").write_text(json.dumps(info, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def read_stage(folder: Path) -> dict | None:
    path = folder / "stage.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def stage_info(kind: str, set_name: str, model: str, questions: list[str], samples: int, ollama: Ollama | None,
               tools: list[dict] | None = None, **extra) -> dict:
    return {
        "kind": kind, "set": set_name, "model": model, "questions": questions, "samples": samples,
        "ollama_version": ollama.version() if ollama else None,
        "git_commit": git_commit(), "code_sha256": code_hash(),
        "client": f"ollmcp {OLLMCP_VERSION}", **extra, **({"tools": tools} if tools is not None else {}),
    }
