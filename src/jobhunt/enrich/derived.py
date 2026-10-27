"""The only writer of derived data: posting_enrichments, enrichment_skills, enrichment_salaries, document_runs,
profile_suggestions, skill_embeddings, link_judgments, link_relations, skill_expansions and link_measurements.

Each run or judgment is added once and never edited; extracting or judging again adds a new one. The caller
owns the transaction.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import insert, select
from sqlalchemy.engine import Connection

from ..db import (
    document_runs,
    enrichment_salaries,
    enrichment_skills,
    link_judgments,
    link_measurements,
    link_relations,
    posting_enrichments,
    profile_suggestions,
    skill_embeddings,
    skill_expansions,
)
from ..userdata import name_key
from .pipeline import DocumentResult, RunResult

RUN_ORIGINS = ("app", "eval")


def save_run(
    conn: Connection, job_id: int, snapshot_id: int, model: str, pipeline: str, result: RunResult, origin: str
) -> int:
    """Store a run (succeeded or failed) with its items; returns the run's id.

    `origin` is 'app' for runs the job queue makes, which the app uses, and 'eval' for runs `jobhunt eval` makes,
    which only the eval reads.
    """
    if origin not in RUN_ORIGINS:
        raise ValueError(f"unknown run origin {origin!r}")
    run_id = conn.execute(
        insert(posting_enrichments).values(
            job_id=job_id,
            snapshot_id=snapshot_id,
            model=model,
            pipeline=pipeline,
            status=result.status,
            error=result.error,
            started_at=result.started_at,
            finished_at=result.finished_at,
            output_json=json.dumps(result.trace, ensure_ascii=False),
            origin=origin,
        )
    ).inserted_primary_key[0]
    if result.skills:
        conn.execute(
            insert(enrichment_skills),
            [
                {
                    "enrichment_id": run_id,
                    "position": position,
                    "name": c.item.name,
                    "key": name_key(c.item.name),
                    "importance": c.item.importance,
                    "kind": c.item.kind,
                    "quote": c.item.quote,
                    "start_offset": c.start,
                    "end_offset": c.end,
                    "verified": c.verified,
                }
                for position, c in enumerate(result.skills)
            ],
        )
    if result.salaries:
        conn.execute(
            insert(enrichment_salaries),
            [
                {
                    "enrichment_id": run_id,
                    "position": position,
                    "min_amount": c.item.min,
                    "max_amount": c.item.max,
                    "currency": c.item.currency,
                    "period": c.item.period,
                    "location": c.item.location,
                    "basis": c.item.basis,
                    "quote": c.item.quote,
                    "start_offset": c.start,
                    "end_offset": c.end,
                    "verified": c.verified,
                }
                for position, c in enumerate(result.salaries)
            ],
        )
    return run_id


def save_document_run(
    conn: Connection, document_id: int, text_sha256: str, model: str, pipeline: str, result: DocumentResult
) -> int:
    """Store a document run (succeeded or failed) and, for a succeeded one, a profile_suggestions row per verified
    suggestion, numbered within its kind; returns the run's id. output_json holds the trace, with the unverified
    items."""
    run_id = conn.execute(
        insert(document_runs).values(
            document_id=document_id,
            text_sha256=text_sha256,
            model=model,
            pipeline=pipeline,
            status=result.status,
            error=result.error,
            started_at=result.started_at,
            finished_at=result.finished_at,
            output_json=json.dumps(result.trace, ensure_ascii=False),
        )
    ).inserted_primary_key[0]
    rows = [
        {"run_id": run_id, "kind": kind, "position": position, "payload_json": json.dumps(payload, ensure_ascii=False)}
        for kind, payloads in (result.suggestions or {}).items() if result.status == "succeeded"
        for position, payload in enumerate(payloads)
    ]
    if rows:
        conn.execute(insert(profile_suggestions), rows)
    return run_id


def save_embeddings(conn: Connection, model: str, vectors: dict[str, list[float]]) -> None:
    """Store a vector per text key for a model; keys it already has are left as they are."""
    from .links import pack

    have = set(
        conn.execute(
            select(skill_embeddings.c.text_key).where(
                skill_embeddings.c.model == model, skill_embeddings.c.text_key.in_(list(vectors))
            )
        ).scalars()
    )
    rows = [{"model": model, "text_key": k, "vector": pack(v)} for k, v in vectors.items() if k not in have]
    if rows:
        conn.execute(insert(skill_embeddings), rows)


def save_judgment(
    conn: Connection, item, model: str, embed_model: str, pipeline: str, status: str, error: str | None,
    relations: dict[int, str], output: dict,
) -> int:
    """Store one judgment of a posting skill (links.Planned) and the relation judged for each candidate."""
    judgment_id = conn.execute(
        insert(link_judgments).values(
            posting_key=item.key,
            posting_name=item.name,
            model=model,
            embed_model=embed_model,
            pipeline=pipeline,
            candidates_json=candidates_json(item.candidates),
            status=status,
            error=error,
            created_at=datetime.now(UTC),
            output_json=json.dumps(output),
        )
    ).inserted_primary_key[0]
    similarity = {c.skill_id: c.similarity for c in item.candidates}
    if relations:
        conn.execute(
            insert(link_relations),
            [
                {
                    "judgment_id": judgment_id,
                    "skill_id": skill_id,
                    "relation": relation,
                    "similarity": similarity[skill_id],
                }
                for skill_id, relation in relations.items()
            ],
        )
    return judgment_id


def candidates_json(candidates) -> str:
    """links.Candidate list, in shortlist order; `pair` is the most similar pair of phrases, when known."""
    return json.dumps([
        {"skill_id": c.skill_id, "name": c.name, "similarity": c.similarity}
        | ({"pair": list(c.pair)} if c.pair else {})
        for c in candidates
    ])


def save_expansion(
    conn: Connection, item, step: str, model: str, status: str, error: str | None, phrases: list[str], output: dict
) -> int:
    """Store one expansion of a skill (expand.Wanted): its cleaned phrasings and the raw response."""
    return conn.execute(
        insert(skill_expansions).values(
            side=item.side,
            skill_key=item.key,
            skill_name=item.name,
            context=item.context,
            step=step,
            model=model,
            status=status,
            error=error,
            phrases_json=json.dumps(phrases, ensure_ascii=False),
            created_at=datetime.now(UTC),
            output_json=json.dumps(output, ensure_ascii=False),
        )
    ).inserted_primary_key[0]


def save_measurement(
    conn: Connection, item, judge: str, model: str, embed_model: str, status: str, error: str | None,
    relations: dict[int, str], output: dict,
) -> int:
    """Store one judgment made by link measurement (links.Planned), apart from the app's judgments."""
    return conn.execute(
        insert(link_measurements).values(
            posting_key=item.key,
            posting_name=item.name,
            judge=judge,
            model=model,
            embed_model=embed_model,
            candidates_json=candidates_json(item.candidates),
            status=status,
            error=error,
            relations_json=json.dumps({str(k): v for k, v in relations.items()}),
            created_at=datetime.now(UTC),
            output_json=json.dumps(output),
        )
    ).inserted_primary_key[0]
