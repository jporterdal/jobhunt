"""The privacy check. Test values that look personal are built at runtime, so this file never matches its own
patterns."""

import subprocess

import pytest

from jobhunt import privacy, userdata
from jobhunt.cli import main
from jobhunt.db import init_db, make_engine

from .conftest import add_posting

EMAIL_DOMAIN = "real-" + "domain.com"
JOB_ID = "4" + "1" * 9
HOME = "/ho" + "me/" + "jdoe" + "/project"


def seed(engine):
    with engine.begin() as conn:
        userdata.add_detail(conn, "contact", "Lakeshore Cottage Road 12", label="Address")
        userdata.add_record(
            conn, {"kind": "degree", "title": "BSc in Basket Weaving", "organisation": "Northgate University"}
        )
        userdata.add_record(conn, {"kind": "role", "title": "Ab", "organisation": "Zed"})
        userdata.create_application(conn, "Welder", "Quillworks Ltd")
    job_id = add_posting(engine)
    with engine.begin() as conn:
        userdata.set_notes(conn, job_id, "Ask about the secret handshake")
        userdata.add_tag(conn, job_id, "dream job")


def test_terms_come_from_the_database_by_category(engine):
    seed(engine)

    terms = privacy.database_terms(engine)

    assert terms["northgate university"] == "record organisation"
    assert terms["bsc in basket weaving"] == "record title"
    assert terms["lakeshore cottage road 12"] == "profile detail"
    assert terms["ask about the secret handshake"] == "posting note"
    assert terms["dream job"] == "tag"
    assert "ab" not in terms and "zed" not in terms


def test_a_database_not_at_head_is_refused_unchanged(empty_engine):
    with pytest.raises(privacy.PrivacyError, match="schema version"):
        privacy.database_terms(empty_engine)


def test_the_database_file_is_not_changed(tmp_path):
    url = f"sqlite:///{tmp_path / 'jobhunt.db'}"
    engine = make_engine(url)
    init_db(engine)
    seed(engine)
    engine.dispose()
    path = tmp_path / "jobhunt.db"
    before, mtime = path.read_bytes(), path.stat().st_mtime_ns

    readonly = privacy.open_database(url)
    terms = privacy.database_terms(readonly)
    readonly.dispose()

    assert "northgate university" in terms
    assert path.read_bytes() == before and path.stat().st_mtime_ns == mtime


def test_a_missing_sqlite_file_is_not_created(tmp_path):
    assert privacy.open_database(f"sqlite:///{tmp_path / 'none.db'}") is None
    assert not (tmp_path / "none.db").exists()


def scan(text, terms=None, allowed=None, path="docs/a.md"):
    scanner = privacy.Scanner(privacy.Terms(terms or {}), allowed or privacy.Allowed())
    return scanner.scan_text(path, text), scanner


def test_case_and_spacing_dont_hide_a_value():
    findings, _ = scan("see ada  QUILL here", {"ada quill": "contact"})

    assert [(f.category, f.line, f.column) for f in findings] == [("contact", 1, 5)]


def test_a_value_matches_whole_words_only():
    findings, _ = scan("the Daleks came; Dale did not", {"dale": "contact"})

    assert [f.column for f in findings] == [18]


def test_a_value_after_an_escape_in_source_is_found():
    findings, _ = scan('text = "EDUCATION\\nDalen\\tthen"', {"dalen": "contact"})

    assert len(findings) == 1


def test_values_under_four_characters_are_dropped():
    assert scan("Zed and Ab", {"zed": "contact", "ab": "contact"})[0] == []


def test_private_terms_are_added():
    terms = privacy.Terms({**{"northgate": "record organisation"}, **privacy.read_terms_from(["Old Employer Inc"])})

    findings, _ = scan("worked at old employer inc once", terms.by_value)

    assert [f.category for f in findings] == ["private term"]


def test_a_generic_posting_title_is_allowed():
    allowed = privacy.Allowed([("", "Data Scientist")])

    findings, scanner = scan("e.g. a Data Scientist role", {"data scientist": "posting title"}, allowed)

    assert findings == [] and scanner.suppressed == 1


def test_an_allow_entry_applies_only_under_its_prefix():
    allowed = privacy.Allowed([("openspec/", "Data Scientist")])
    terms = {"data scientist": "posting title"}

    assert scan("Data Scientist", terms, allowed, path="openspec/specs/x.md")[0] == []
    assert len(scan("Data Scientist", terms, allowed, path="src/x.py")[0]) == 1


def test_an_inline_marker_cannot_hide_a_database_value():
    findings, _ = scan("Northgate University  # privacy: allow", {"northgate university": "record organisation"})

    assert len(findings) == 1


def test_a_real_job_id_is_found():
    findings, _ = scan(f"https://jobs.example.com/view/{JOB_ID}/")

    assert [f.category for f in findings] == ["job id"]


def test_synthetic_values_pass():
    text = "9000000001 jane@example.com +1 555 555 0100 jane@acme.example 1234+jane@users.noreply.github.com"

    assert scan(text)[0] == []


def test_real_looking_emails_and_phones_are_found():
    findings, _ = scan(f"write to jane@{EMAIL_DOMAIN} or call 902-" + "555-" + "1234")

    assert [f.category for f in findings] == ["email", "phone"]


def test_a_package_version_is_not_an_email():
    assert scan("npx @fission-ai/openspec@1.13.0 validate")[0] == []


def test_a_home_path_is_found():
    assert [f.category for f in scan(f'"cwd": "{HOME}"')[0]] == ["home path"]


def test_a_pattern_finding_can_be_marked_allowed_and_is_counted():
    findings, scanner = scan(f"{HOME}  # privacy: allow")

    assert findings == [] and scanner.suppressed == 1


@pytest.mark.parametrize(
    "path, forbidden",
    [
        ("notes.pdf", True), ("a/b/cv.ODT", True), ("x.sqlite3", True), ("data/anything.txt", True),
        ("page.html", True), ("src/jobhunt/web/templates/a.html", False), ("tests/fixtures/synthetic/p.html", False),
        ("file:Zone.Identifier", True), ("src/jobhunt/db.py", False),
    ],
)
def test_forbidden_file_kinds(path, forbidden):
    assert privacy.forbidden_kind(path) is forbidden


# --- Git scopes ---


def run_git(repo, *args, **env):
    import os

    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env={**os.environ, **env})
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    run_git(path, "config", "user.name", "tester")
    run_git(path, "config", "user.email", "tester@example.com")
    return path


def commit(repo, files, message="change", **env):
    for name, content in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", message, **env)
    return run_git(repo, "rev-parse", "HEAD").strip()


TERMS = {"northgate university": "record organisation"}


def test_a_value_removed_from_the_tree_is_still_in_history(repo):
    first = commit(repo, {"spec.md": "studied at Northgate University\n"})
    commit(repo, {"spec.md": "studied at Example University\n"})

    assert privacy.check(repo, TERMS).findings == []
    found = privacy.check(repo, TERMS, history=True).findings
    assert [(f.category, f.path, f.commit) for f in found] == [("record organisation", "spec.md", first)]


def test_a_personal_author_email_is_found(repo):
    sha = commit(
        repo, {"a.txt": "x\n"}, message="fine",
        GIT_AUTHOR_EMAIL=f"jane@{EMAIL_DOMAIN}", GIT_AUTHOR_NAME="Jane", GIT_COMMITTER_EMAIL="c@example.com",
    )
    private = privacy.read_terms_from([f"jane@{EMAIL_DOMAIN}"])

    found = privacy.check(repo, private_terms=private, history=True).findings

    assert [(f.category, f.commit) for f in found] == [("commit identity", sha)]


def test_a_public_handle_can_be_allowed_as_the_commit_identity(repo):
    commit(
        repo, {"a.txt": "x\n", "b.txt": "made by janedoe-dev\n"},
        GIT_AUTHOR_NAME="janedoe-dev", GIT_AUTHOR_EMAIL="1+janedoe-dev@users.noreply.github.com",
        GIT_COMMITTER_NAME="janedoe-dev", GIT_COMMITTER_EMAIL="1+janedoe-dev@users.noreply.github.com",
    )
    private = privacy.read_terms_from(["janedoe-dev"])
    allowed = privacy.Allowed([(privacy.COMMIT_IDENTITY, "janedoe-dev")])

    report = privacy.check(repo, allowed=allowed, private_terms=private, history=True)

    # Allowed in the commit's identity, still found in the file.
    assert [(f.category, f.path) for f in report.findings] == [("private term", "b.txt")] * 2
    assert report.suppressed == 4


def test_a_commit_message_is_scanned(repo):
    commit(repo, {"a.txt": "x\n"}, message="job " + JOB_ID)

    found = privacy.check(repo, history=True).findings

    assert [(f.category, f.path) for f in found] == [("job id", "<commit message>")]


def test_an_unignored_backup_is_found(repo):
    commit(repo, {"a.txt": "x\n"})
    (repo / "data.bak").mkdir()
    (repo / "data.bak" / "cv.odt").write_bytes(b"PK")
    (repo / "data.bak" / "jobhunt.db").write_bytes(b"SQLite")

    found = privacy.check(repo).findings

    assert [(f.category, f.path) for f in found] == [("unignored personal file", "data.bak/")]


def test_an_ignored_backup_passes(repo):
    commit(repo, {".gitignore": "data.bak/\n"})
    (repo / "data.bak").mkdir()
    (repo / "data.bak" / "cv.odt").write_bytes(b"PK")

    assert privacy.check(repo).findings == []


def test_synthetic_fixtures_pass_as_files_but_are_still_scanned(repo):
    commit(repo, {"tests/fixtures/synthetic/two_jobs.html": f"<p>call {JOB_ID}</p>\n"})

    found = privacy.check(repo).findings

    assert [f.category for f in found] == ["job id"]


def test_staged_scope_reads_the_staged_version(repo):
    commit(repo, {"a.md": "clean\n"})
    (repo / "a.md").write_text("Northgate University\n", encoding="utf-8")
    run_git(repo, "add", "a.md")
    (repo / "a.md").write_text("clean again\n", encoding="utf-8")

    assert [f.category for f in privacy.check(repo, TERMS, staged=True).findings] == ["record organisation"]
    assert privacy.check(repo, TERMS).findings == []


def test_a_tracked_allow_file_is_reported(repo):
    commit(repo, {"data/privacy-allow.txt": "Data Scientist\n"})

    found = privacy.check(repo, protect=[repo / "data" / "privacy-allow.txt"]).findings

    assert "tracked private file" in {f.category for f in found}


def test_a_term_in_a_file_name_is_found(repo):
    commit(repo, {"notes-northgate university.md": "x\n"})

    assert [f.category for f in privacy.check(repo, TERMS).findings] == ["record organisation"]


# --- The command ---


@pytest.fixture
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'jobhunt.db'}"
    engine = make_engine(url)
    init_db(engine)
    seed(engine)
    engine.dispose()
    return url


def test_ci_logs_stay_clean(repo, capsys):
    commit(repo, {"a.md": f"mail jane@{EMAIL_DOMAIN}\n"})

    code = main(["privacy-check", "--repo", str(repo), "--patterns-only"])

    out = capsys.readouterr().out
    assert code == 1
    assert "a.md:1:6: email: j… (" in out and EMAIL_DOMAIN not in out
    assert "email: 1" in out

    main(["privacy-check", "--repo", str(repo), "--patterns-only", "--show"])
    assert EMAIL_DOMAIN in capsys.readouterr().out


def test_no_database_runs_patterns_only(repo, tmp_path, capsys):
    commit(repo, {"a.md": "Northgate University\n"})

    code = main(["privacy-check", "--repo", str(repo), "--db", f"sqlite:///{tmp_path / 'missing.db'}"])

    assert code == 0
    assert "were not checked" in capsys.readouterr().out
    assert not (tmp_path / "missing.db").exists()


def test_database_values_and_private_terms_are_checked(repo, db_url, capsys):
    (repo / "data").mkdir()
    (repo / "data" / "privacy-terms.txt").write_text("# employers\nOld Employer Inc\n", encoding="utf-8")
    commit(repo, {".gitignore": "data/\n", "a.md": "Northgate University and Old Employer Inc\n"})

    code = main(["privacy-check", "--repo", str(repo), "--db", db_url])

    out = capsys.readouterr().out
    assert code == 1
    assert "record organisation: 1" in out and "private term: 1" in out


def test_a_database_not_at_head_exits_2(repo, tmp_path, capsys):
    import sqlite3

    path = tmp_path / "old.db"
    sqlite3.connect(path).execute("create table t (x)").connection.commit()
    commit(repo, {"a.md": "x\n"})

    code = main(["privacy-check", "--repo", str(repo), "--db", f"sqlite:///{path}"])

    assert code == 2
    assert "schema version" in capsys.readouterr().err


def test_a_clean_repository_exits_0(repo, capsys):
    commit(repo, {"a.md": "nothing personal\n"})

    assert main(["privacy-check", "--repo", str(repo), "--patterns-only"]) == 0
    assert "No findings." in capsys.readouterr().out
