"""Pipeline contracts, validation and the steps, all without a database or a model server."""

import pytest

from jobhunt.enrich import pipeline, validate
from jobhunt.enrich.pipeline import Cancelled, SalaryItem, Segment, SkillItem, StepFailed, run_pipeline
from jobhunt.enrich.salary import PayLineExtractor
from jobhunt.enrich.segment import LineClassifier, RuleSegmenter, batches, is_heading, lines
from jobhunt.enrich.skills import ATOMIC_V2

from .conftest import posting_text
from .fakes import FakeLLM, label_lines, skill

PAY_TEXT = (
    "The base salary in the range of $175,000 – $200,000 USD (Example Metro, EX), "
    "$110,000 – $130,000 CAD (Example City, EX) is offered."
)

POSTING = """About us
We build data platforms.

Requirements
- Expert-level Python, with experience in MLflow and Spark
- 5+ years with SQL
- Familiarity with Terraform is a plus

Nice to have
- Airflow

What We Offer
Pay: $120k–150k per year
"""


def segments_by_label(text, segs):
    return {label: [text[s.start:s.end] for s in segs if s.label == label] for label in pipeline.LABELS}


# --- Contracts and registry (3.1) ---


def test_pipeline_id_is_stable():
    steps = pipeline.steps_for("llm-lines")
    assert pipeline.pipeline_id(steps) == "seg=llm-lines@2 skills=atomic@2 salary=paylines@1 validate=v@3"
    assert pipeline.pipeline_id(pipeline.steps_for("llm-lines")) == pipeline.pipeline_id(steps)
    assert pipeline.steps_from_id(pipeline.pipeline_id(steps)) == steps


def test_registry_lists_segmenters():
    assert set(pipeline.segmenters()) == {"rules", "llm-lines"}


def test_registry_lists_skill_extractors_by_version():
    assert list(pipeline.skill_extractors()) == ["atomic@2"]


def test_registry_holds_the_apps_method_and_at_most_one_candidate():
    registered = pipeline.skill_extractors()
    assert pipeline.CURRENT_SKILLS in registered and len(registered) <= 2


def test_app_skill_version_resolves():
    pid = "seg=llm-lines@2 skills=atomic@2 salary=paylines@1 validate=v@3"
    steps = pipeline.steps_from_id(pid)
    assert steps.skills is ATOMIC_V2 and pipeline.pipeline_id(steps) == pid


def test_unknown_pipeline_rejected():
    with pytest.raises(ValueError):
        pipeline.steps_from_id("seg=gone@1 skills=atomic@2 salary=paylines@1 validate=v@3")
    with pytest.raises(ValueError):
        pipeline.steps_from_id("seg=rules@9 skills=atomic@2 salary=paylines@1 validate=v@3")
    with pytest.raises(ValueError):
        pipeline.steps_from_id("seg=llm-lines@2 skills=atomic@3 salary=paylines@1 validate=v@3")
    with pytest.raises(ValueError):  # measured, not adopted, deleted
        pipeline.steps_from_id("seg=llm-lines@2 skills=atomic@4 salary=paylines@1 validate=v@3")


def test_conform_rejects_wrong_shapes():
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    assert pipeline.conform("x", {"n": 3}, schema) == {"n": 3}
    for bad in ({}, {"n": "3"}, {"n": True}, []):
        with pytest.raises(StepFailed) as err:
            pipeline.conform("x", bad, schema)
        assert err.value.step == "x"


# --- Validator (3.2) ---


def test_normalise_maps_back_to_raw():
    text = "  Expert–level   “Python”\n"
    norm, positions = validate.normalise(text)
    assert norm == 'expert-level "python"'
    assert len(positions) == len(norm)
    assert text[positions[0]] == "E" and text[positions[-1]] == "”"


def test_quote_found_despite_case_dashes_and_spaces():
    start, end = validate.locate(PAY_TEXT, "$175,000 - $200,000  usd")
    assert PAY_TEXT[start:end] == "$175,000 – $200,000 USD"


def test_quote_looked_for_in_source_line_first():
    text = "Python is used\n- Python 3"
    second_line = (15, len(text))
    assert validate.locate(text, "python", second_line) == (17, 23)
    assert validate.locate(text, "python") == (0, 6)
    assert validate.locate(text, "Python is", second_line) == (0, 9)  # falls back to the whole text


def test_short_quote_lands_on_whole_word():
    text = "Specific tooling: Git, CI, containers"
    start, end = validate.locate(text, "CI", (0, len(text)))
    assert text[start:end] == "CI" and start == text.index("CI,")


def test_quote_next_to_punctuation_is_whole_word():
    text = "Strong C#/.NET skills"
    assert validate.locate(text, "C#") == (7, 9)


def test_partial_word_quote_falls_back_to_first_occurrence():
    text = "Run Kubernetes clusters"
    [checked] = validate.check_skills(text, [SkillItem("Kubernetes", "required", "technical", "Kubernete")])
    assert checked.verified and (checked.start, checked.end) == (4, 13)


def test_whole_word_on_source_line_wins_over_earlier_line():
    text = "Python is used\n- Python 3"
    assert validate.locate(text, "Python", (15, len(text))) == (17, 23)


def test_partial_word_on_source_line_beats_whole_word_elsewhere():
    text = "Use CI daily\n- discipline"
    assert validate.locate(text, "ci", (13, len(text))) == (18, 20)  # inside "discipline", on the source line
    assert validate.locate(text, "ci") == (4, 6)


def test_invented_quote_is_unverified():
    [checked] = validate.check_skills(
        PAY_TEXT, [SkillItem("Kubernetes", "required", "technical", "Kubernetes clusters")]
    )
    assert not checked.verified and checked.start is None


def _checked(name, importance, verified=True, quote=None):
    return validate.Checked(SkillItem(name, importance, "technical", quote or name), verified, 0 if verified else None)


def test_merge_keeps_required_over_preferred():
    merged = validate.merge_skills(
        [_checked("AWS Bedrock", "preferred"), _checked("AWS Bedrock", "required", quote="Bedrock")]
    )
    assert [(c.item.importance, c.item.quote) for c in merged] == [("required", "Bedrock")]


def test_merge_keeps_first_of_equal_importance():
    merged = validate.merge_skills(
        [_checked("Optimization", "required", quote="first"), _checked("Optimization", "required", quote="second")]
    )
    assert [c.item.quote for c in merged] == ["first"]


def test_merge_leaves_unverified_items_out():
    items = [_checked("Python", "preferred"), _checked("Python", "required", verified=False)]
    assert validate.merge_skills(items) == items


def test_merge_compares_skill_keys():
    merged = validate.merge_skills(
        [
            _checked("Machine  learning", "required"),
            _checked("machine learning", "preferred"),
            _checked("SQL", "preferred"),
        ]
    )
    assert [c.item.name for c in merged] == ["Machine  learning", "SQL"]


@pytest.mark.parametrize(
    "quote, amounts",
    [
        ("$175,000 - $200,000", [175000, 200000]),
        ("175000 to 200000", [175000, 200000]),
        ("$175k-$200K", [175000, 200000]),
        ("$175–200k", [175000, 200000]),
        ("$2,950.40 - $3,610.00 Bi-Weekly", [2950.4, 3610]),
    ],
)
def test_amounts_in_written_forms(quote, amounts):
    written = validate.amounts_in(quote)
    assert all(validate.amount_in(a, written) for a in amounts)


def test_two_currency_sentence_verifies_both_ranges():
    items = [
        SalaryItem(
            175000, 200000, "USD", "year", "Example Metro, EX", "base", "$175,000 - $200,000 USD (Example Metro, EX)"
        ),
        SalaryItem(110000, 130000, "CAD", "year", "Example City, EX", "base", "$110,000 - $130,000 CAD"),
    ]
    checked = validate.check_salaries(PAY_TEXT, items)
    assert [c.verified for c in checked] == [True, True]
    assert PAY_TEXT[checked[1].start:checked[1].end] == "$110,000 – $130,000 CAD"


def test_wrong_amount_is_unverified():
    item = SalaryItem(175000, 210000, "USD", "year", None, "base", "$175,000 - $200,000")
    assert not validate.check_salaries(PAY_TEXT, [item])[0].verified


def test_tolerance_is_half_a_percent():
    assert validate.amount_in(175500, [175000])
    assert not validate.amount_in(176000, [175000])


# --- run_pipeline (3.3) ---


def full_llm(**extra):
    return FakeLLM(
        {
            "lines": [
                label_lines({"Python": "required", "SQL": "required", "Terraform": "preferred", "Airflow": "preferred"})
            ],
            "skills": [
                {"skills": [skill(1, "Python", "Python"), skill(1, "MLflow", "MLflow"), skill(2, "SQL", "SQL")]},
                {
                    "skills": [
                        skill(1, "Terraform", "Terraform"),
                        skill(2, "Airflow", "Airflow"),
                        skill(2, "Go", "Golang"),
                    ]
                },
            ],
            "ranges": [{"ranges": [_range(120000, 150000, "$120k–150k")]}],
        },
        **extra,
    )


def _range(lo, hi, quote, currency="USD"):
    return {
        "min": lo,
        "max": hi,
        "currency": currency,
        "period": "year",
        "location": None,
        "basis": "base",
        "quote": quote,
    }


def test_successful_run():
    llm = full_llm()
    result = run_pipeline(POSTING, llm, pipeline.steps_for("llm-lines"))
    assert result.status == "succeeded" and result.error is None
    verified = [(c.item.name, c.item.importance) for c in result.skills if c.verified]
    assert verified == [
        ("Python", "required"),
        ("MLflow", "required"),
        ("SQL", "required"),
        ("Terraform", "preferred"),
        ("Airflow", "preferred"),
    ]
    assert [c.item.name for c in result.skills if not c.verified] == ["Go"]
    [pay] = result.salaries
    assert pay.verified and (pay.item.min, pay.item.max) == (120000, 150000)
    trace = result.trace
    assert [s["step"] for s in trace["steps"]] == ["segment", "skills", "salary"]
    assert [len(s["calls"]) for s in trace["steps"]] == [1, 2, 1]
    assert all("seconds" in s for s in trace["steps"])
    assert {tuple(s) for s in trace["segments"]} >= {(s.start, s.end, s.label) for s in result.segments}
    assert result.seconds >= 0


def test_same_skill_in_both_groups_is_suggested_once_at_required():
    llm = FakeLLM(
        {
            "lines": [label_lines({"Python": "required", "Terraform": "preferred"})],
            "skills": [{"skills": [skill(1, "Python", "Python")]}, {"skills": [skill(1, "python", "Terraform")]}],
        }
    )
    result = run_pipeline(POSTING, llm, pipeline.steps_for("llm-lines"))
    assert [(c.item.name, c.item.importance) for c in result.skills] == [("Python", "required")]
    assert [(i["name"], i["importance"]) for i in result.trace["items"]["skills"]] == [
        ("Python", "required"),
        ("python", "preferred"),
    ]


def test_failed_step_is_a_failed_result():
    llm = full_llm()
    llm.responses["ranges"] = [{"ranges": [{"min": "lots"}]}]
    result = run_pipeline(POSTING, llm, pipeline.steps_for("llm-lines"))
    assert result.status == "failed"
    assert result.error.startswith("salary: response does not match the schema")
    assert result.skills == [] and result.salaries == []
    assert result.trace["error"] == result.error


def test_client_error_is_named_after_the_step():
    class Broken(FakeLLM):
        def chat_json(self, system, user, schema):
            raise StepFailed(None, "Ollama returned HTTP 500")

    result = run_pipeline(POSTING, Broken(), pipeline.steps_for("llm-lines"))
    assert result.error == "segment: Ollama returned HTTP 500"


def test_cancelled_between_steps():
    llm = full_llm()
    stops = iter([False, True])
    with pytest.raises(Cancelled):
        run_pipeline(POSTING, llm, pipeline.steps_for("llm-lines"), should_stop=lambda: next(stops))
    assert llm.calls("lines") == 1 and llm.calls("skills") == 0


# --- rules@2 (4.1) ---


def test_rules_segmenter_on_headings():
    segs = RuleSegmenter().segment(POSTING, FakeLLM())
    by_label = segments_by_label(POSTING, segs)
    assert by_label["required"] == ["- Expert-level Python, with experience in MLflow and Spark", "- 5+ years with SQL"]
    assert by_label["preferred"] == ["- Familiarity with Terraform is a plus", "- Airflow"]
    assert "Requirements" in by_label["other"] and "Pay: $120k–150k per year" not in by_label["required"]


DUTIES = """About the role
We are a small team in Example City.

Key Responsibilities
- Lead the supervised fine-tuning work
- Experience with Kubeflow is a plus

What you'll do:
- Integrate AI agents into the SDLC via AWS Bedrock
"""


def test_rules_segmenter_duty_headings_start_required():
    by_label = segments_by_label(DUTIES, RuleSegmenter().segment(DUTIES, FakeLLM()))
    assert by_label["required"] == [
        "- Lead the supervised fine-tuning work",
        "- Integrate AI agents into the SDLC via AWS Bedrock",
    ]
    assert by_label["preferred"] == ["- Experience with Kubeflow is a plus"]
    assert "We are a small team in Example City." in by_label["other"]


def test_rules_segmenter_on_posting_fixtures():
    expected = {
        "data-automation.json": {"other"},  # "What will you do?" is not one of the duty headings
        "senior-ai-engineer.json": {"other", "required"},  # "Key Responsibilities"
        "innovation-lab.json": {"other", "required"},  # "Responsibilities"
    }
    for name, labels in expected.items():
        text = posting_text(name)
        segs = RuleSegmenter().segment(text, FakeLLM())
        assert [(s.start, s.end) for s in segs] == lines(text)
        assert {s.label for s in segs} == labels
        assert all(text[s.start:s.end] == text[s.start:s.end].strip() for s in segs)
    text = posting_text("senior-ai-engineer.json")
    required = segments_by_label(text, RuleSegmenter().segment(text, FakeLLM()))["required"]
    assert required == ["- Design scalable AI/ML solutions", "- Work with Python, ReactJS, AWS"]


def test_heading_rules():
    assert is_heading("What you'll bring")
    assert is_heading("Preferred qualifications:")
    assert is_heading("Responsibilities")
    assert not is_heading("You have strong experience with Python and modern data tooling")
    assert not is_heading("- Requirements gathering with stakeholders")
    assert not is_heading("Employment Type: Full time")


def test_rules_segmenter_needs_no_model():
    llm = FakeLLM()
    RuleSegmenter().segment(POSTING, llm)
    assert llm.requests == []


# --- llm-lines@2 (4.2) ---


def test_line_classifier_spans_are_exact_lines():
    llm = FakeLLM({"lines": [{"lines": [{"line": 5, "label": "required"}, {"line": 99, "label": "required"}]}]})
    segs = LineClassifier().segment(POSTING, llm)
    assert [(s.start, s.end) for s in segs] == lines(POSTING)
    labelled = [(POSTING[s.start:s.end], s.label) for s in segs if s.label != "other"]
    assert labelled == [("- 5+ years with SQL", "required")]  # line 99 is out of range; omitted lines are other
    request = llm.requests[0]
    assert request.user.splitlines()[0] == "1: About us"
    assert request.schema["properties"]["lines"]["items"]["properties"]["label"]["enum"] == [
        "required",
        "preferred",
        "other",
    ]


def test_line_classifier_counts_duties_as_required():
    llm = FakeLLM()
    LineClassifier().segment(POSTING, llm)
    system = llm.requests[0].system
    required = next(line for line in system.splitlines() if line.startswith('- "required"'))
    other = next(line for line in system.splitlines() if line.startswith('- "other"'))
    assert "work the hire will do" in required and "duty bullets" in system
    assert "duties" not in other and "company" in other


def test_line_classifier_batches_long_text():
    text = "\n".join(f"- Requirement number {i} for the role" for i in range(1, 201))
    llm = FakeLLM(num_ctx=2048)
    LineClassifier().segment(text, llm)
    asked = [[int(row.split(":")[0]) for row in r.user.splitlines()] for r in llm.requests]
    assert len(asked) > 1
    assert sum(asked, []) == list(range(1, 201))
    budget = 0.6 * 2048 * 3.5
    assert all(len(r.user) <= budget for r in llm.requests)


def test_batches_keep_short_text_whole():
    assert batches(["1: a", "2: b"], 8192) == [[0, 1]]


def test_line_classifier_bad_label_fails():
    llm = FakeLLM({"lines": [{"lines": [{"line": 1, "label": "maybe"}]}]})
    with pytest.raises(StepFailed) as err:
        LineClassifier().segment(POSTING, llm)
    assert err.value.step == "segment"


# --- atomic extractor ---


def rule_segments():
    return RuleSegmenter().segment(POSTING, FakeLLM())


@pytest.mark.parametrize("extractor", [ATOMIC_V2], ids=["atomic@2"])
def test_list_splitting_is_passed_through(extractor):
    llm = FakeLLM(
        {
            "skills": [
                {
                    "skills": [
                        skill(1, "Python", "Expert-level Python"),
                        skill(1, "MLflow", "MLflow"),
                        skill(1, "Spark", "Spark"),
                    ]
                },
                {"skills": [skill(2, "Airflow", "Airflow")]},
            ]
        }
    )
    items = extractor.extract(POSTING, rule_segments(), llm)
    assert [(i.name, i.importance) for i in items] == [
        ("Python", "required"),
        ("MLflow", "required"),
        ("Spark", "required"),
        ("Airflow", "preferred"),
    ]
    first_line = lines(POSTING)[3]
    assert items[0].source == first_line
    assert llm.requests[0].user.startswith("1: - Expert-level Python")


def test_default_prompt_is_atomic_2():
    llm = FakeLLM({"skills": [{"skills": [skill(1, "Python", "Python")]}]})
    ATOMIC_V2.extract(POSTING, rule_segments(), llm)
    system = llm.requests[0].system
    for kind in ('"technical"', '"soft"', '"qualification"'):
        assert kind in system
    for level in ('"PhD"', '"Master\'s degree"', '"Advanced degree"'):
        assert level in system
    assert "work they describe" in system
    assert "everyday activities" not in system and "Leave out only the excluded words" not in system
    assert pipeline.skill_extractors()[pipeline.CURRENT_SKILLS] is ATOMIC_V2


@pytest.mark.parametrize("extractor", [ATOMIC_V2], ids=["atomic@2"])
def test_qualification_kind_accepted_and_domain_rejected(extractor):
    degree = {"skills": [skill(1, "Master's degree", "Expert-level", kind="qualification")]}
    llm = FakeLLM({"skills": [degree]})
    items = extractor.extract(POSTING, rule_segments(), llm)
    assert {(i.name, i.kind) for i in items} == {("Master's degree", "qualification")}
    llm = FakeLLM({"skills": [{"skills": [skill(1, "Fintech", "Python", kind="domain")]}]})
    with pytest.raises(StepFailed) as err:
        extractor.extract(POSTING, rule_segments(), llm)
    assert err.value.step == "skills" and "is not one of" in err.value.message


@pytest.mark.parametrize("extractor", [ATOMIC_V2], ids=["atomic@2"])
def test_empty_group_retried_once(extractor):
    llm = FakeLLM(
        {
            "skills": [
                {"skills": []},
                {"skills": [skill(1, "Python", "Python")]},
                {"skills": [skill(1, "Airflow", "Airflow")]},
            ]
        }
    )
    items = extractor.extract(POSTING, rule_segments(), llm)
    assert [i.name for i in items] == ["Python", "Airflow"]
    assert llm.calls("skills") == 3
    assert "required section" in llm.requests[1].user and "section" not in llm.requests[0].user


@pytest.mark.parametrize("extractor", [ATOMIC_V2], ids=["atomic@2"])
def test_two_empty_results_fail(extractor):
    llm = FakeLLM({"skills": [{"skills": []}]})
    with pytest.raises(StepFailed) as err:
        extractor.extract(POSTING, rule_segments(), llm)
    assert str(err.value) == "no skills were extracted from the required lines"
    assert llm.calls("skills") == 2


@pytest.mark.parametrize("extractor", [ATOMIC_V2], ids=["atomic@2"])
def test_no_call_for_empty_groups(extractor):
    llm = FakeLLM()
    assert extractor.extract(POSTING, [Segment(0, 8, "other")], llm) == []
    assert llm.requests == []


# --- paylines@1 (4.4) ---


def test_no_request_without_pay():
    llm = FakeLLM()
    text = posting_text("data-automation.json")
    assert PayLineExtractor().extract(text, llm) == []
    assert llm.requests == []


def test_only_pay_lines_are_sent():
    llm = FakeLLM()
    PayLineExtractor().extract(POSTING, llm)
    assert llm.requests[0].user == "Pay: $120k–150k per year"


def test_two_ranges_from_two_currency_sentence():
    llm = FakeLLM(
        {
            "ranges": [
                {
                    "ranges": [
                        _range(175000, 200000, "$175,000 - $200,000 USD (Example Metro, EX)")
                        | {"location": "Example Metro, EX"},
                        _range(110000, 130000, "$110,000 - $130,000 CAD (Example City, EX)", "cad")
                        | {"location": "Example City, EX"},
                    ]
                }
            ]
        }
    )
    items = PayLineExtractor().extract(PAY_TEXT, llm)
    assert [(i.min, i.max, i.currency, i.period, i.location) for i in items] == [
        (175000, 200000, "USD", "year", "Example Metro, EX"),
        (110000, 130000, "CAD", "year", "Example City, EX"),
    ]
    assert all(c.verified for c in validate.check_salaries(PAY_TEXT, items))
    assert llm.requests[0].schema["properties"]["ranges"]["items"]["properties"]["basis"]["enum"] == [
        "base",
        "ote",
        "unclear",
    ]
