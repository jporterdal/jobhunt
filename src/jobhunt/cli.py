"""Command line: `jobhunt import [PATH ...]`, `jobhunt serve`, `jobhunt eval`, `jobhunt profile reset`,
`jobhunt privacy-check` and `jobhunt demo`."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .db import DEFAULT_DB_URL, init_db, make_engine
from .documents import DEFAULT_DOCUMENTS_DIR
from .enrich.ollama import DEFAULT_URL as DEFAULT_OLLAMA_URL
from .enrich.pipeline import segmenters, skill_extractors
from .importer import discover, format_report, import_files

DEFAULT_INBOX = "inbox"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def _storage_args(parser: argparse.ArgumentParser) -> None:
    """--inbox and --db, defaulting the same way for every command."""
    parser.add_argument(
        "--inbox",
        type=Path,
        default=Path(os.environ.get("JOBHUNT_INBOX", DEFAULT_INBOX)),
        help="folder of files to import (default: $JOBHUNT_INBOX or ./inbox)",
    )
    _db_arg(parser)


def _db_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db",
        default=os.environ.get("JOBHUNT_DB_URL", DEFAULT_DB_URL),
        help=f"database URL (default: $JOBHUNT_DB_URL or {DEFAULT_DB_URL})",
    )


def _ollama_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--ollama-url",
        default=os.environ.get("JOBHUNT_OLLAMA_URL", DEFAULT_OLLAMA_URL),
        help="Ollama server, the only address model requests go to "
        f"(default: $JOBHUNT_OLLAMA_URL or {DEFAULT_OLLAMA_URL})",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobhunt", description="Collect and annotate job postings and track applications."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    imp = commands.add_parser(
        "import",
        help="import job postings from files",
        description=(
            "Import job postings through the installed parsers. Every parser is tried on every file, and a file is "
            "imported only when exactly one accepts it. The built-in parser reads posting files: one JSON object "
            'per posting, with "format": "jobhunt-posting" and "version": 1. '
            "With no PATH, every file in the inbox is imported and then moved to "
            "inbox/processed/ or inbox/rejected/. Explicit PATHs are imported in place."
        ),
    )
    imp.add_argument("paths", nargs="*", type=Path, metavar="PATH", help="file(s) to import in place")
    _storage_args(imp)

    serve = commands.add_parser(
        "serve",
        help="run the local web interface",
        description="Serve the web interface for browsing postings and recording your own data. "
        "It has no authentication, so it listens on 127.0.0.1 unless told otherwise.",
    )
    serve.add_argument("--host", default=DEFAULT_HOST, help=f"address to listen on (default: {DEFAULT_HOST})")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port (default: {DEFAULT_PORT})")
    _storage_args(serve)
    serve.add_argument(
        "--documents",
        type=Path,
        default=Path(os.environ.get("JOBHUNT_DOCUMENTS", DEFAULT_DOCUMENTS_DIR)),
        help=f"folder for uploaded documents (default: $JOBHUNT_DOCUMENTS or {DEFAULT_DOCUMENTS_DIR})",
    )
    _ollama_arg(serve)
    serve.add_argument("--debug", action="store_true", help="Flask debugger and auto-reload (development only)")

    ev = commands.add_parser(
        "eval",
        help="measure skill extraction against labelled postings",
        description="Run skill extraction on every posting whose skill labelling is flagged complete and report "
        "precision (with unjudged suggestions counted apart), recall against the marks you selected, and where "
        "missed skills were lost. "
        "Stored runs for the same snapshot, model and pipeline are reused; new runs are stored. "
        "Given several skill extraction methods, it reports them side by side with the marks only some found. "
        "With --links it measures skill linking against the links you set on the links page instead.",
    )
    ev.add_argument("--model", help="model to evaluate (default: the one chosen in Settings)")
    ev.add_argument("--segmenter", choices=sorted(segmenters()), help="segmentation method (default: from Settings)")
    ev.add_argument(
        "--skills",
        metavar="METHOD[,METHOD...]",
        help=f"skill extraction method(s) to evaluate and compare, from {', '.join(skill_extractors())} "
        "(default: from Settings)",
    )
    ev.add_argument(
        "--fresh", action="store_true", help="run extraction (or link judging) again even when a stored result exists"
    )
    ev.add_argument("--json", action="store_true", help="print the report as JSON")
    ev.add_argument(
        "--links", action="store_true",
        help="measure skill linking against your link overrides instead of skill extraction (development use)",
    )
    ev.add_argument(
        "--retrieval", metavar="METHOD[,METHOD...]",
        help="with --links: candidate-finding method(s) to measure, from "
        f"{', '.join(links_registry().RETRIEVALS)} (default: the app's)",
    )
    ev.add_argument(
        "--judge",
        metavar="VERSION[,VERSION...]",
        help=f"with --links: judging version(s) to measure, from {', '.join(links_registry().JUDGES)} "
        "(default: the app's)",
    )
    ev.add_argument("--dry-run", action="store_true", help="with --links: state the model requests needed and stop")
    ev.add_argument(
        "--all-skills",
        action="store_true",
        help="with --links: also judge every other posting skill, and report how many links would differ from "
        "the app's",
    )
    _db_arg(ev)
    _ollama_arg(ev)

    profile = commands.add_parser("profile", help="maintain the profile")
    profile_commands = profile.add_subparsers(dest="profile_command", required=True)
    reset = profile_commands.add_parser(
        "reset",
        help="delete every record, claim and highlight (for comparing a fresh extraction on a copy)",
        description="Delete every record, claim and highlight, with their lines, sources, grounds and coverage, from "
        "the database, without remembering them as rejected. Profile details, aliases, remembered rejections, link "
        "overrides, posting data and documents stay. Meant for a copy of the database: back up data/ first.",
    )
    reset.add_argument("--yes", action="store_true", help="confirm the deletion")
    _db_arg(reset)

    privacy = commands.add_parser(
        "privacy-check",
        help="find personal values and personal-looking patterns in a repository",
        description="Scan a git repository for the values in your database, the lines of a private term file and "
        "personal-looking patterns (posting IDs, emails, phone numbers, home paths), and for files that must not be "
        "committed. Findings show a masked value unless --show is given. Exit 0: nothing found; 1: findings; "
        "2: usage or database problem. The database is only read.",
    )
    privacy.add_argument(
        "--repo", type=Path, default=Path("."), help="repository to scan (default: the current folder)"
    )
    privacy.add_argument("--staged", action="store_true", help="scan the staged version of each staged file only")
    privacy.add_argument("--history", action="store_true", help="also scan every commit reachable from any ref")
    privacy.add_argument(
        "--patterns-only", action="store_true",
        help="check patterns and file kinds only: no database values, no private terms",
    )
    privacy.add_argument("--show", action="store_true", help="print the full value of each finding")
    privacy.add_argument(
        "--terms", type=Path, help="private term file (default: data/privacy-terms.txt in the repository)"
    )
    privacy.add_argument("--allow", type=Path, help="allow file (default: data/privacy-allow.txt in the repository)")
    _db_arg(privacy)

    from .demo.seed import DEFAULT_DB_URL as DEMO_DB_URL
    from .demo.seed import DEFAULT_DOCUMENTS_DIR as DEMO_DOCUMENTS_DIR

    demo = commands.add_parser(
        "demo",
        help="build a demo database with a fictional person's job search",
        description="Build a separate demo database and documents folder: invented postings, a profile, notes, "
        "applications, model suggestions and skill links (from scripted answers: no model server or network is "
        "used) and a saved tailored CV. The defaults never point at your own data, and a database or folder that "
        "already holds data is refused unchanged.",
    )
    demo.add_argument("--db", default=DEMO_DB_URL, help=f"database URL for the demo (default: {DEMO_DB_URL})")
    demo.add_argument(
        "--documents", type=Path, default=Path(DEMO_DOCUMENTS_DIR),
        help=f"documents folder for the demo (default: {DEMO_DOCUMENTS_DIR})",
    )
    return parser


def links_registry():
    from .enrich import links

    return links


def main(argv: list[str] | None = None) -> int:
    from .migrate import TooOld
    from .privacy import PrivacyError

    args = build_parser().parse_args(argv)
    try:
        if args.command == "privacy-check":
            return _privacy_check(args)
        if args.command == "serve":
            return _serve(args)
        if args.command == "eval":
            return _eval(args)
        if args.command == "profile":
            return _profile_reset(args)
        if args.command == "demo":
            return _demo(args)
        return _import(args)
    except (TooOld, PrivacyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _privacy_check(args: argparse.Namespace) -> int:
    from sqlalchemy.exc import SQLAlchemyError

    from . import privacy

    repo = args.repo
    terms_file = args.terms or repo / privacy.DEFAULT_TERMS_FILE
    allow_file = args.allow or repo / privacy.DEFAULT_ALLOW_FILE
    terms: dict[str, str] = {}
    private: dict[str, str] = {}
    notices: list[str] = []
    if args.patterns_only:
        notices.append(
            "Personal values and private terms were not checked (--patterns-only); patterns and file kinds were."
        )
    else:
        try:
            engine = privacy.open_database(args.db)
            if engine is None:
                notices.append(f"No database at {args.db}: personal values and private terms were not checked; "
                               "patterns and file kinds were.")
            else:
                try:
                    terms = privacy.database_terms(engine)
                finally:
                    engine.dispose()
                private = privacy.read_terms(terms_file)
        except SQLAlchemyError as error:
            raise privacy.PrivacyError(f"cannot read the database: {error}") from error
    report = privacy.check(
        repo, terms, privacy.Allowed.from_file(allow_file), staged=args.staged, history=args.history,
        private_terms=private, protect=(terms_file, allow_file), notices=notices,
    )
    print(report.format(show=args.show))
    return report.exit_code


def _demo(args: argparse.Namespace) -> int:
    from .demo import seed

    engine = make_engine(args.db)
    try:
        reason = seed.refusal(engine, args.documents)
        if reason is not None:
            print(f"error: {reason}; the demo needs an empty database and documents folder. Nothing was changed.",
                  file=sys.stderr)
            return 2
        init_db(engine)
        built = seed.build(engine, args.documents)
    finally:
        engine.dispose()
    print(f"Built the demo: {built.postings} postings ({built.snapshots} captures), {built.runs} model runs and a "
          "saved CV, for a fictional person.")
    print("Open it with:")
    print(f"  jobhunt serve --db {args.db} --documents {args.documents}")
    return 0


def _profile_reset(args: argparse.Namespace) -> int:
    from .userdata import reset_knowledge_base

    if not args.yes:
        print(f"This deletes every record, claim and highlight in {args.db}. Run it again with --yes to confirm.",
              file=sys.stderr)
        return 2
    engine = make_engine(args.db)
    try:
        init_db(engine)
        with engine.begin() as conn:
            counts = reset_knowledge_base(conn)
    finally:
        engine.dispose()
    print(
        f"Deleted {counts['records']} records, {counts['claims']} claims and {counts['highlights']} highlights "
        f"from {args.db}."
    )
    print("Kept: profile details, aliases, remembered rejections, link overrides, postings and documents.")
    return 0


def _import(args: argparse.Namespace) -> int:
    from .parsers import installed as installed_parsers

    installed = installed_parsers()
    if args.paths:
        missing = [str(p) for p in args.paths if not p.is_file()]
        if missing:
            print("error: file not found: " + ", ".join(missing), file=sys.stderr)
            return 2
        paths, inbox = args.paths, None
    else:
        if not args.inbox.is_dir():
            print(f"error: inbox folder not found: {args.inbox}", file=sys.stderr)
            return 2
        paths, inbox = discover(args.inbox, installed.parsers), args.inbox
        if not paths:
            print(f"Nothing to import in {args.inbox}")
            return 0

    engine = make_engine(args.db)
    try:
        init_db(engine)
        print(format_report(import_files(engine, paths, inbox, installed.parsers), installed.errors))
    finally:
        engine.dispose()
    return 0


def _serve(args: argparse.Namespace) -> int:
    from .enrich.jobs import Worker
    from .enrich.ollama import OllamaClient
    from .web import create_app

    engine = make_engine(args.db)
    worker = None
    try:
        init_db(engine)
        client = OllamaClient(args.ollama_url)
        app = create_app(engine, args.inbox, args.documents, host=args.host, port=args.port, ollama=client)
        shown_host = f"[{args.host}]" if ":" in args.host else args.host
        print(f"jobhunt: serving http://{shown_host}:{args.port}/")
        print(f"  database:  {engine.url.render_as_string(hide_password=True)}")
        print(f"  inbox:     {args.inbox}")
        print(f"  documents: {args.documents}  (back it up together with the database)")
        print(f"  ollama:    {args.ollama_url}")
        if args.host not in LOOPBACK_HOSTS:
            print(
                f"warning: listening on {args.host}, not loopback. The interface has no authentication: "
                "anyone who can reach this address can read and change your data.",
                file=sys.stderr,
            )
        # The debug reloader's parent process only watches files; the worker runs in the child it serves from.
        if not args.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
            worker = Worker(engine, client)
            worker.start()
        app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=args.debug, threaded=True)
    finally:
        if worker is not None:
            worker.stop()
            worker.join(timeout=5)
        engine.dispose()
    return 0


NO_LABELS = """No labelled postings yet, so there is nothing to measure against.
To label a posting: open it in `jobhunt serve`, select each skill it asks for in the description and mark it
(required or preferred), then click "Labelling complete". Label 5-10 postings this way before extracting them:
recall counts only the marks you select yourself, so select them before seeing the model's suggestions."""


NO_OVERRIDES = """No links set by hand yet, so there is nothing to measure linking against.
Measuring needs links set on the links page (/profile/links): for posting skills, choose the profile skill and
relation you would link them to, or "no link"."""


def _split(value: str | None) -> list[str]:
    return [m.strip() for m in (value or "").split(",") if m.strip()]


def _eval_links(args: argparse.Namespace) -> int:
    from .enrich import link_eval
    from .enrich.ollama import OllamaClient
    from .enrich.pipeline import StepFailed, Unreachable

    if args.skills or args.segmenter:
        print(
            "error: --skills and --segmenter measure skill extraction; they can't be used with --links", file=sys.stderr
        )
        return 1
    retrievals, judges = _split(args.retrieval), _split(args.judge)
    if len(set(retrievals)) < len(retrievals) or len(set(judges)) < len(judges):
        print("error: each method and version may be given once", file=sys.stderr)
        return 1
    try:
        link_eval.check_methods(retrievals, judges)
    except link_eval.UnknownMethod as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    engine = make_engine(args.db)
    client = OllamaClient(args.ollama_url)
    try:
        init_db(engine)
        plan = link_eval.plan(engine, client, retrievals, judges, args.model, args.fresh, args.all_skills)
        print(plan.statement(), file=sys.stderr)
        if args.dry_run:
            return 0
        if plan.needs_requests:
            client.version()  # refuse before making any request
        report = link_eval.execute(engine, client, plan, progress=lambda m: print(m, file=sys.stderr))
    except link_eval.NoReference:
        print(NO_OVERRIDES, file=sys.stderr)
        return 1
    except link_eval.NoModel as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Unreachable as exc:
        print(
            f"error: Ollama is unreachable ({exc}); results made so far are stored and will be reused", file=sys.stderr
        )
        return 1
    except StepFailed as exc:
        print(f"error: {exc.step}: {exc.message}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(link_eval.report_json(report) if args.json else link_eval.format_text(report))
    return 0


def _eval(args: argparse.Namespace) -> int:
    from .enrich import evaluate

    if args.links:
        return _eval_links(args)
    if args.retrieval or args.judge or args.dry_run or args.all_skills:
        print("error: --retrieval, --judge, --dry-run and --all-skills need --links", file=sys.stderr)
        return 1
    from .enrich.ollama import OllamaClient
    from .enrich.pipeline import Unreachable

    methods = [m.strip() for m in (args.skills or "").split(",") if m.strip()] or [None]
    try:
        for method in methods:
            if method is not None:
                evaluate.check_skills(method)
    except evaluate.UnknownSkills as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if len(set(methods)) < len(methods):
        print("error: each skill extraction method may be given once", file=sys.stderr)
        return 1

    engine = make_engine(args.db)
    reports = []
    try:
        init_db(engine)
        plans = [evaluate.plan(engine, args.model, args.segmenter, method, args.fresh) for method in methods]
        for p in plans:
            print(f"{p.skills}: {len(p.todo)} new runs, {len(p.labelled) - len(p.todo)} reused", file=sys.stderr)
        client = OllamaClient(args.ollama_url)
        if any(p.todo for p in plans):
            client.version()  # refuse before running any method
        for p in plans:
            reports.append(evaluate.execute(engine, client, p))
    except evaluate.NoLabelledPostings:
        print(NO_LABELS, file=sys.stderr)
        return 1
    except evaluate.NoModel:
        print("error: no model chosen; pass --model or choose one in Settings", file=sys.stderr)
        return 1
    except Unreachable as exc:
        stored = [r.skills for r in reports if r.new_runs]
        written = f"new runs were stored for {', '.join(stored)} only" if stored else "nothing was written"
        print(f"error: Ollama is unreachable ({exc}); {written}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    if len(reports) == 1:
        print(evaluate.report_json(reports[0]) if args.json else reports[0].format_text())
    else:
        print(evaluate.comparison_json(reports) if args.json else evaluate.comparison_text(reports))
    return 0


if __name__ == "__main__":
    sys.exit(main())
