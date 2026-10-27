"""The demo's fictional person, Jane Doe, as plain data: her profile, her notes on the postings, her applications
and contacts, the skills the scripted model finds in postings, and the relations it judges. Every value comes from
the cast in docs/fictional-data.md."""

from __future__ import annotations

from datetime import UTC, date, datetime

# Every time the demo writes is fixed relative to this, so two builds match and screenshots don't change.
DEMO_DATE = datetime(2026, 10, 15, 17, 0, tzinfo=UTC)

# --- What the scripted model finds in postings ---

# The headings of the demo postings, and the label the scripted segmenter gives the lines under each.
SECTIONS = {
    "About the role": "other",
    "What you'll do": "required",
    "What you bring": "required",
    "Nice to have": "preferred",
    "Pay and benefits": "other",
}

# A posting asks for a skill wherever its text names one of these terms (whole words, any case): term -> (name,
# kind). The scripted extractor quotes the text as written, so every suggestion is verified against the posting.
SKILL_TERMS = {
    "Python": ("Python", "technical"),
    "SQL": ("SQL", "technical"),
    "PostgreSQL": ("PostgreSQL", "technical"),
    "scikit-learn": ("scikit-learn", "technical"),
    "sklearn": ("sklearn", "technical"),
    "PyTorch": ("PyTorch", "technical"),
    "machine learning": ("Machine learning", "technical"),
    "statistical modeling": ("Statistical modeling", "technical"),
    "statistical modelling": ("Statistical modelling", "technical"),
    "forecasting": ("Forecasting", "technical"),
    "time series": ("Time series", "technical"),
    "data visualization": ("Data visualization", "technical"),
    "data visualisation": ("Data visualisation", "technical"),
    "Tableau": ("Tableau", "technical"),
    "Power BI": ("Power BI", "technical"),
    "A/B testing": ("A/B testing", "technical"),
    "data pipelines": ("Data pipelines", "technical"),
    "Airflow": ("Airflow", "technical"),
    "dbt": ("dbt", "technical"),
    "Spark": ("Spark", "technical"),
    "Kafka": ("Kafka", "technical"),
    "Terraform": ("Terraform", "technical"),
    "experiment tracking": ("Experiment tracking", "technical"),
    "model monitoring": ("Model monitoring", "technical"),
    "MLflow": ("MLflow", "technical"),
    "Docker": ("Docker", "technical"),
    "Kubernetes": ("Kubernetes", "technical"),
    "CI/CD": ("CI/CD", "technical"),
    "AWS": ("AWS", "technical"),
    "Azure": ("Azure", "technical"),
    "Linux": ("Linux", "technical"),
    "Git": ("Git", "technical"),
    "REST APIs": ("REST APIs", "technical"),
    "large language models": ("Large language models", "technical"),
    "transformers": ("Transformers", "technical"),
    "NLP": ("NLP", "technical"),
    "stakeholder management": ("Stakeholder management", "soft"),
    "mentoring": ("Mentoring", "soft"),
    "communication": ("Communication", "soft"),
    "technical writing": ("Technical writing", "soft"),
    "teaching": ("Teaching", "soft"),
    "Master's degree": ("Master's degree", "qualification"),
    "PhD": ("PhD", "qualification"),
}

# How the scripted judge relates a posting skill to a shortlisted profile skill (by name key); any other pair is
# "none". Only names that look alike reach the judge, since the demo's embeddings compare letters.
RELATIONS = {
    ("statistical modeling", "statistical modelling"): "same",
    ("data visualisation", "data visualization"): "same",
    ("time series", "time series analysis"): "same",
    ("model monitoring", "monitoring"): "general",
    ("spark", "spark sql"): "specific",
}

# --- The profile ---

DETAILS = [
    ("name", "Jane Doe", None),
    ("headline", "Data scientist moving into machine learning engineering", None),
    ("contact", "jane@example.com", "Email"),
    ("contact", "+1 555 555 0100", "Phone"),
    ("contact", "https://github.com/janedoe-example", "GitHub"),
    ("summary", "Data scientist with seven years in insurance and banking analytics: forecasting, risk models and "
                "the dashboards people use to act on them.", None),
    ("goal", "A machine learning engineering role on a small product team, building models that run in production.",
     None),
]

# Records by key: fields for userdata.add_record, plus lines, sources and the record it is part of.
RECORDS = {
    "insurance": dict(
        kind="role", title="Data Scientist", organisation="Example Insurance", location="Example City, EX",
        start_date="2022-03", ongoing=True,
        lines=["Build claim-frequency and forecasting models in Python on a PostgreSQL warehouse",
               "Run A/B testing of renewal letters with the marketing team",
               "Present model results to underwriting leads; stakeholder management across three departments",
               "Mentoring two junior analysts"],
    ),
    "bank": dict(
        kind="role", title="Data Analyst", organisation="Example Bank", location="Example City, EX",
        start_date="2019-06", end_date="2022-02",
        lines=["Built weekly risk dashboards in Tableau and set data visualization standards for the team",
               "Wrote SQL and Spark SQL jobs for loan-level reporting",
               "Automated monthly reporting in Python"],
    ),
    "contract": dict(
        kind="role", title="Contract Analyst", organisation="Example Advisory", start_date="2021-05",
        end_date="2021-08", disclosure="private",
        lines=["Pricing analysis for a client under a non-disclosure agreement"],
    ),
    "triage": dict(
        kind="project", title="Claim triage model", organisation="Example Insurance", start_date="2023-01",
        end_date="2023-09", part_of="insurance",
        lines=["A machine learning model that routes incoming claims to the right adjuster",
               "scikit-learn and PyTorch prototypes, packaged with Docker and versioned in Git",
               "Monitoring dashboards for drift and routing accuracy"],
        sources=["https://github.com/janedoe-example/claim-triage"],
    ),
    "forecast": dict(
        kind="project", title="Open claim-volume forecasts", start_date="2024-02", end_date="2024-05",
        lines=["A small Python package for hierarchical time series analysis of claim counts"],
        sources=["https://github.com/janedoe-example/claim-forecasts"],
    ),
    "paper": dict(
        kind="publication", title="Forecasting claim volumes with hierarchical models",
        organisation="EXCONF 2024 (Applied Optimization Track)", start_date="2024-07",
        lines=["Lead author; technical writing and the forecasting experiments"],
        sources=["https://doi.org/10.5555/3600000.3600001"],
    ),
    "msc": dict(
        kind="degree", title="MSc Statistics", organisation="Example University", start_date="2017-09",
        end_date="2019-05",
        lines=["Thesis: statistical modelling of seasonal demand", "Time series analysis and Bayesian methods"],
    ),
    "bsc": dict(
        kind="degree", title="BSc Mathematics", organisation="Example Polytechnic", start_date="2013-09",
        end_date="2017-05",
    ),
    "course": dict(
        kind="course", title="Introduction to Programming (COMP 1000)", organisation="Example University",
        start_date="2018-09", end_date="2018-12",
        lines=["Teaching assistant: weekly Python labs for 60 first-year students"],
    ),
    "award": dict(
        kind="award", title="Graduate Scholarship", organisation="Example University", start_date="2018",
    ),
    "talk": dict(
        kind="event", title="Forecasting with small data", organisation="Example City Data Meetup",
        start_date="2025-03", lines=["A 20-minute talk on hierarchical forecasting for small teams"],
    ),
}

# Claims: skill name -> (level, grounds as (record key, quote in one of its lines, or None for a hand-made ground)).
CLAIMS = {
    "Python": ("expert", [("insurance", "Python"), ("bank", "Python"), ("forecast", "Python")]),
    "SQL": ("proficient", [("bank", "SQL")]),
    "PostgreSQL": ("proficient", [("insurance", "PostgreSQL")]),
    "scikit-learn": ("proficient", [("triage", "scikit-learn")]),
    "PyTorch": ("familiar", [("triage", "PyTorch")]),
    "Machine learning": ("proficient", [("triage", "machine learning")]),
    "Statistical modelling": ("expert", [("msc", "statistical modelling"), ("paper", None)]),
    "Forecasting": ("expert", [("insurance", "forecasting"), ("paper", "forecasting")]),
    "Time series analysis": ("proficient", [("msc", "Time series analysis"), ("forecast", "time series analysis")]),
    "Data visualization": ("proficient", [("bank", "data visualization")]),
    "Tableau": ("proficient", [("bank", "Tableau")]),
    "A/B testing": ("familiar", [("insurance", "A/B testing")]),
    "Spark SQL": ("familiar", [("bank", "Spark SQL")]),
    "Git": ("proficient", [("triage", "Git")]),
    "Docker": ("learning", [("triage", "Docker")]),
    "Monitoring": ("familiar", [("triage", "Monitoring")]),
    "Stakeholder management": ("proficient", [("insurance", "stakeholder management")]),
    "Mentoring": ("familiar", [("insurance", "Mentoring")]),
    "Technical writing": ("proficient", [("paper", "technical writing")]),
    "Teaching": ("proficient", [("course", "Teaching")]),
    "Master's degree": ("expert", [("msc", None)]),
    "AWS": ("learning", []),  # no record shows it yet: the profile flags it
    "Kubernetes": ("missing", []),  # answered "don't have it"
}

# Skills merged into another (its name becomes an alias): merged name -> kept name.
ALIASES = {"sklearn": "scikit-learn", "Postgres": "PostgreSQL"}

# CV wording: text -> the claims it covers.
HIGHLIGHTS = {
    "Built and deployed a claim triage model in Python and scikit-learn that routes 40% of claims automatically":
        ["Python", "scikit-learn", "Machine learning"],
    "Forecast monthly claim volumes with hierarchical time series models, cutting reserve error by a fifth":
        ["Forecasting", "Time series analysis", "Statistical modelling"],
    "Designed the bank's risk dashboards in Tableau, used weekly by 30 managers": ["Tableau", "Data visualization"],
    "Ran A/B tests on renewal letters that lifted renewals by 3 points": ["A/B testing"],
    "Explained model results to underwriting and finance leads every quarter": ["Stakeholder management"],
    "Wrote SQL and Spark SQL jobs behind loan-level reporting": ["SQL", "Spark SQL"],
    "Mentored two junior analysts through their first modelling projects": ["Mentoring"],
    "Taught weekly programming labs for 60 first-year students": ["Teaching"],
    "Published a peer-reviewed paper on hierarchical forecasting": ["Technical writing", "Statistical modelling"],
    # Names a private record's organisation: the CV proposal flags it and leaves it unticked.
    "Priced commercial policies for an Example Advisory client": ["SQL"],
}

# The user's own links, set where the judge wouldn't see the pair: posting skill -> (profile skill, relation), or
# None for "no link".
LINK_OVERRIDES = {
    "Power BI": ("Tableau", "related"),
    "Communication": ("Stakeholder management", "related"),
    "Terraform": None,
}

# --- Notes on postings, by external ID ---

TRIAGE = {
    "9000000101": dict(interest=5, fit=4, tags=["shortlist", "hybrid"],
                       notes="Team of six. Ask how on-call works for the **model monitoring** duties."),
    "9000000102": dict(interest=3, fit=4, tags=["finance"]),
    "9000000103": dict(interest=3, fit=5, tags=["remote"],
                       notes="Second capture added a salary range and Power BI."),
    "9000000104": dict(interest=4, fit=3, tags=["remote"]),
    "9000000105": dict(interest=4, fit=4, tags=["shortlist", "hybrid"]),
    "9000000106": dict(interest=4, fit=2, tags=["remote", "stretch"]),
    "9000000107": dict(interest=2, fit=3),
    "9000000108": dict(interest=3, fit=3),
    "9000000109": dict(interest=1, fit=3),
    "9000000110": dict(interest=4, fit=2, tags=["remote", "stretch"]),
}

# Skills the user marked by hand: external ID -> [(skill name, quote, importance)].
MARKS = {
    "9000000102": [("Credit risk modelling", "credit risk models", "required")],
    "9000000106": [("Alerting", "alerting", "required")],
}

# Suggestions the user accepted, and rejected with a reason: external ID -> skill names.
ACCEPTED = {"9000000101": ["Python", "Airflow", "MLflow"]}
REJECTED = {"9000000107": [("Communication", "not-a-skill")], "9000000109": [("Teaching", "not-for-me")]}

# Dismissed postings: external ID -> (dismiss reason key, comment).
DISMISSED = {"9000000109": ("wrong domain", "Teaching full time isn't the direction I want.")}

# Applications: external ID -> (events as (kind, date, note)), next action and its due date, pay notes.
APPLICATIONS = {
    "9000000101": dict(
        events=[("applied", date(2026, 10, 2), "Applied through the company site with a tailored CV."),
                ("screening", date(2026, 10, 7), "Call with the recruiter, 30 minutes."),
                ("interviewing", date(2026, 10, 14), "Technical interview with two engineers.")],
        next_action=("Send the claim-triage write-up to the recruiter", date(2026, 10, 17)),
        compensation="Recruiter said the band tops out at $125,000.",
    ),
    "9000000104": dict(
        events=[("applied", date(2026, 10, 5), None),
                ("rejected", date(2026, 10, 13), "Looking for more streaming experience.")],
    ),
}

COMPANY = dict(name="Example Labs", website_url="https://www.example.com", careers_url="https://careers.example.com",
               notes="Retail forecasting; about 80 people. Two openings this month.")

CONTACT = dict(name="Sam Lee", emails=["sam.lee@example.com"], role="Technical recruiter",
               profile_url="https://www.example.com/people/sam-lee",
               notes="Prefers email. Mentioned the team is hiring two engineers.")

COVER_LETTER = (
    "cover-letter-example-labs.md",
    "Cover letter, Example Labs",
    """Dear hiring team,

I'm applying for the Machine Learning Engineer role. At Example Insurance I built a claim triage model in
Python and scikit-learn that now routes 40% of incoming claims, and I'd like to bring that production
experience to your forecasting products.

Jane Doe
""",
)

# The posting the demo's saved CV is tailored for.
TAILORED_FOR = "9000000101"
