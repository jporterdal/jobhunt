"""Baseline: the whole schema, with the default dismiss reasons.

Revision ID: 0010_baseline
Revises:
Create Date: 2026-10-18

The revisions before this one (0001-0010) were squashed into it once every known database had reached
0010_baseline. A database at an older revision, or made before revisions existed, is refused (migrate.TooOld);
upgrade it first with a release from before the baseline. Downgrading drops every table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from jobhunt.db import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0010_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_DISMISS_REASONS = (
    ("Too senior", "too senior"),
    ("Too junior", "too junior"),
    ("Location or on-site", "location or on-site"),
    ("Compensation", "compensation"),
    ("Wrong domain", "wrong domain"),
    ("Skills mismatch", "skills mismatch"),
    ("Company", "company"),
    ("Other", "other"),
)


def upgrade() -> None:
    op.create_table('app_settings',
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('companies',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('website_url', sa.Text(), nullable=True),
    sa.Column('careers_url', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )
    op.create_table('dismiss_reasons',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )
    op.create_table('documents',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('original_filename', sa.Text(), nullable=False),
    sa.Column('media_type', sa.Text(), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('uploaded_at', UTCDateTime(), nullable=False),
    sa.Column('text_content', sa.Text(), nullable=True),
    sa.Column('text_status', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_documents_sha256'), ['sha256'], unique=False)

    op.create_table('link_judgments',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('posting_key', sa.Text(), nullable=False),
    sa.Column('posting_name', sa.Text(), nullable=False),
    sa.Column('model', sa.Text(), nullable=False),
    sa.Column('embed_model', sa.Text(), nullable=False),
    sa.Column('pipeline', sa.Text(), nullable=False),
    sa.Column('candidates_json', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('output_json', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('link_judgments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_link_judgments_posting_key'), ['posting_key'], unique=False)

    op.create_table('link_measurements',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('posting_key', sa.Text(), nullable=False),
    sa.Column('posting_name', sa.Text(), nullable=False),
    sa.Column('judge', sa.Text(), nullable=False),
    sa.Column('model', sa.Text(), nullable=False),
    sa.Column('embed_model', sa.Text(), nullable=False),
    sa.Column('candidates_json', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('relations_json', sa.Text(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('output_json', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('link_measurements', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_link_measurements_posting_key'), ['posting_key'], unique=False)

    op.create_table('postings',
    sa.Column('job_id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('source', sa.String(length=100), nullable=False),
    sa.Column('external_id', sa.String(length=200), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('first_seen_at', UTCDateTime(), nullable=False),
    sa.Column('last_seen_at', UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('job_id'),
    sa.UniqueConstraint('source', 'external_id', name='uq_postings_source_external_id')
    )
    op.create_table('profile_details',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('label', sa.Text(), nullable=True),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('profile_rejections',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('identity', sa.Text(), nullable=False),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('identity')
    )
    op.create_table('skill_embeddings',
    sa.Column('model', sa.Text(), nullable=False),
    sa.Column('text_key', sa.Text(), nullable=False),
    sa.Column('vector', sa.LargeBinary(), nullable=False),
    sa.PrimaryKeyConstraint('model', 'text_key')
    )
    op.create_table('skill_expansions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('side', sa.Text(), nullable=False),
    sa.Column('skill_key', sa.Text(), nullable=False),
    sa.Column('skill_name', sa.Text(), nullable=False),
    sa.Column('context', sa.Text(), nullable=True),
    sa.Column('step', sa.Text(), nullable=False),
    sa.Column('model', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('phrases_json', sa.Text(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('output_json', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('skill_expansions', schema=None) as batch_op:
        batch_op.create_index('ix_skill_expansions_lookup', ['side', 'skill_key', 'step'], unique=False)

    op.create_table('skills',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )
    op.create_table('tags',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('key', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )
    op.create_table('applications',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('company', sa.Text(), nullable=False),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('status_date', sa.Date(), nullable=True),
    sa.Column('next_action', sa.Text(), nullable=True),
    sa.Column('next_action_due', sa.Date(), nullable=True),
    sa.Column('compensation_notes', sa.Text(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['postings.job_id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_id')
    )
    op.create_table('captures',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('source_name', sa.Text(), nullable=False),
    sa.Column('captured_at', UTCDateTime(), nullable=False),
    sa.Column('imported_at', UTCDateTime(), nullable=False),
    sa.Column('raw_gz', sa.LargeBinary(), nullable=False),
    sa.Column('parser', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['job_id'], ['postings.job_id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sha256')
    )
    with op.batch_alter_table('captures', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_captures_job_id'), ['job_id'], unique=False)

    op.create_table('contacts',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('role', sa.Text(), nullable=True),
    sa.Column('profile_url', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('contacts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_contacts_company_id'), ['company_id'], unique=False)

    op.create_table('document_runs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('text_sha256', sa.String(length=64), nullable=False),
    sa.Column('model', sa.Text(), nullable=False),
    sa.Column('pipeline', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('started_at', UTCDateTime(), nullable=False),
    sa.Column('finished_at', UTCDateTime(), nullable=False),
    sa.Column('output_json', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('document_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_document_runs_document_id'), ['document_id'], unique=False)

    op.create_table('link_relations',
    sa.Column('judgment_id', sa.Integer(), nullable=False),
    sa.Column('skill_id', sa.Integer(), nullable=False),
    sa.Column('relation', sa.Text(), nullable=False),
    sa.Column('similarity', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['judgment_id'], ['link_judgments.id'], ),
    sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], ),
    sa.PrimaryKeyConstraint('judgment_id', 'skill_id')
    )
    op.create_table('posting_dismissals',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('dismissed_at', UTCDateTime(), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('restored_at', UTCDateTime(), nullable=True),
    sa.ForeignKeyConstraint(['job_id'], ['postings.job_id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('posting_dismissals', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_posting_dismissals_job_id'), ['job_id'], unique=False)

    op.create_table('posting_tags',
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('tag_id', sa.Integer(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['postings.job_id'], ),
    sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ),
    sa.PrimaryKeyConstraint('job_id', 'tag_id')
    )
    op.create_table('posting_triage',
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('interest', sa.SmallInteger(), nullable=True),
    sa.Column('fit', sa.SmallInteger(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.Column('skills_complete_at', UTCDateTime(), nullable=True),
    sa.Column('skills_first_complete_at', UTCDateTime(), nullable=True),
    sa.ForeignKeyConstraint(['job_id'], ['postings.job_id'], ),
    sa.PrimaryKeyConstraint('job_id')
    )
    op.create_table('rejected_suggestions',
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('skill_key', sa.Text(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['job_id'], ['postings.job_id'], ),
    sa.PrimaryKeyConstraint('job_id', 'skill_key')
    )
    op.create_table('skill_aliases',
    sa.Column('alias_key', sa.Text(), nullable=False),
    sa.Column('skill_id', sa.Integer(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], ),
    sa.PrimaryKeyConstraint('alias_key')
    )
    with op.batch_alter_table('skill_aliases', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_skill_aliases_skill_id'), ['skill_id'], unique=False)

    op.create_table('skill_link_overrides',
    sa.Column('posting_key', sa.Text(), nullable=False),
    sa.Column('skill_id', sa.Integer(), nullable=True),
    sa.Column('relation', sa.Text(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], ),
    sa.PrimaryKeyConstraint('posting_key')
    )
    op.create_table('tailored_cvs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('method', sa.Text(), nullable=False),
    sa.Column('content_version', sa.Integer(), nullable=False),
    sa.Column('match_score', sa.Float(), nullable=True),
    sa.Column('choice_json', sa.Text(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['postings.job_id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('tailored_cvs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tailored_cvs_job_id'), ['job_id'], unique=False)

    op.create_table('application_contacts',
    sa.Column('application_id', sa.Integer(), nullable=False),
    sa.Column('contact_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ),
    sa.PrimaryKeyConstraint('application_id', 'contact_id')
    )
    op.create_table('application_documents',
    sa.Column('application_id', sa.Integer(), nullable=False),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.PrimaryKeyConstraint('application_id', 'document_id')
    )
    op.create_table('application_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('application_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('event_date', sa.Date(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('application_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_application_events_application_id'), ['application_id'], unique=False)

    op.create_table('claims',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('skill_id', sa.Integer(), nullable=False),
    sa.Column('level', sa.Text(), nullable=False),
    sa.Column('level_origin', sa.Text(), nullable=False),
    sa.Column('origin', sa.Text(), nullable=False),
    sa.Column('source_run_id', sa.Integer(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], ),
    sa.ForeignKeyConstraint(['source_run_id'], ['document_runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('skill_id')
    )
    op.create_table('contact_emails',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('contact_id', sa.Integer(), nullable=False),
    sa.Column('email', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('contact_emails', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_contact_emails_contact_id'), ['contact_id'], unique=False)

    op.create_table('highlights',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('origin', sa.Text(), nullable=False),
    sa.Column('source_run_id', sa.Integer(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['source_run_id'], ['document_runs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('posting_dismissal_reasons',
    sa.Column('dismissal_id', sa.Integer(), nullable=False),
    sa.Column('reason_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['dismissal_id'], ['posting_dismissals.id'], ),
    sa.ForeignKeyConstraint(['reason_id'], ['dismiss_reasons.id'], ),
    sa.PrimaryKeyConstraint('dismissal_id', 'reason_id')
    )
    op.create_table('posting_snapshots',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('capture_id', sa.Integer(), nullable=False),
    sa.Column('parser', sa.Text(), nullable=False),
    sa.Column('fingerprint', sa.String(length=64), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('company', sa.Text(), nullable=False),
    sa.Column('location', sa.Text(), nullable=True),
    sa.Column('workplace_type', sa.Text(), nullable=True),
    sa.Column('employment_type', sa.Text(), nullable=True),
    sa.Column('posted_on_estimate', sa.Date(), nullable=True),
    sa.Column('posted_on_precision', sa.Text(), nullable=True),
    sa.Column('description_html', sa.Text(), nullable=False),
    sa.Column('description_text', sa.Text(), nullable=False),
    sa.Column('details_json', sa.Text(), nullable=False),
    sa.Column('volatile_json', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['capture_id'], ['captures.id'], ),
    sa.ForeignKeyConstraint(['job_id'], ['postings.job_id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('posting_snapshots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_posting_snapshots_job_id'), ['job_id'], unique=False)

    op.create_table('profile_suggestions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('payload_json', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['document_runs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('profile_suggestions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_profile_suggestions_run_id'), ['run_id'], unique=False)

    op.create_table('records',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('organisation', sa.Text(), nullable=True),
    sa.Column('location', sa.Text(), nullable=True),
    sa.Column('start_date', sa.Text(), nullable=True),
    sa.Column('end_date', sa.Text(), nullable=True),
    sa.Column('ongoing', sa.Boolean(), nullable=False),
    sa.Column('disclosure', sa.Text(), server_default='public', nullable=False),
    sa.Column('part_of_id', sa.Integer(), nullable=True),
    sa.Column('context_lost_at', UTCDateTime(), nullable=True),
    sa.Column('origin', sa.Text(), nullable=False),
    sa.Column('source_run_id', sa.Integer(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['part_of_id'], ['records.id'], ),
    sa.ForeignKeyConstraint(['source_run_id'], ['document_runs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_records_part_of_id'), ['part_of_id'], unique=False)

    op.create_table('tailored_cv_items',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('cv_id', sa.Integer(), nullable=False),
    sa.Column('section', sa.Text(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('source_kind', sa.Text(), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=True),
    sa.Column('payload_json', sa.Text(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['cv_id'], ['tailored_cvs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('tailored_cv_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tailored_cv_items_cv_id'), ['cv_id'], unique=False)

    op.create_table('claim_records',
    sa.Column('claim_id', sa.Integer(), nullable=False),
    sa.Column('record_id', sa.Integer(), nullable=False),
    sa.Column('quote', sa.Text(), nullable=False),
    sa.Column('origin', sa.Text(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['claim_id'], ['claims.id'], ),
    sa.ForeignKeyConstraint(['record_id'], ['records.id'], ),
    sa.PrimaryKeyConstraint('claim_id', 'record_id')
    )
    with op.batch_alter_table('claim_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_claim_records_record_id'), ['record_id'], unique=False)

    op.create_table('highlight_claims',
    sa.Column('highlight_id', sa.Integer(), nullable=False),
    sa.Column('claim_id', sa.Integer(), nullable=False),
    sa.Column('quote', sa.Text(), nullable=True),
    sa.Column('origin', sa.Text(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['claim_id'], ['claims.id'], ),
    sa.ForeignKeyConstraint(['highlight_id'], ['highlights.id'], ),
    sa.PrimaryKeyConstraint('highlight_id', 'claim_id')
    )
    with op.batch_alter_table('highlight_claims', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_highlight_claims_claim_id'), ['claim_id'], unique=False)

    op.create_table('posting_enrichments',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('snapshot_id', sa.Integer(), nullable=False),
    sa.Column('model', sa.Text(), nullable=False),
    sa.Column('pipeline', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('started_at', UTCDateTime(), nullable=False),
    sa.Column('finished_at', UTCDateTime(), nullable=False),
    sa.Column('output_json', sa.Text(), nullable=False),
    sa.Column('origin', sa.Text(), server_default='app', nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['postings.job_id'], ),
    sa.ForeignKeyConstraint(['snapshot_id'], ['posting_snapshots.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('posting_enrichments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_posting_enrichments_job_id'), ['job_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_posting_enrichments_snapshot_id'), ['snapshot_id'], unique=False)

    op.create_table('posting_skill_marks',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('skill_id', sa.Integer(), nullable=False),
    sa.Column('quote', sa.Text(), nullable=False),
    sa.Column('snapshot_id', sa.Integer(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('importance', sa.Text(), nullable=True),
    sa.Column('origin', sa.Text(), server_default='selection', nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['postings.job_id'], ),
    sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], ),
    sa.ForeignKeyConstraint(['snapshot_id'], ['posting_snapshots.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('posting_skill_marks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_posting_skill_marks_job_id'), ['job_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_posting_skill_marks_skill_id'), ['skill_id'], unique=False)

    op.create_table('record_lines',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('record_id', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('origin', sa.Text(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['record_id'], ['records.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('record_lines', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_record_lines_record_id'), ['record_id'], unique=False)

    op.create_table('record_sources',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('record_id', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('document_id', sa.Integer(), nullable=True),
    sa.Column('origin', sa.Text(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['record_id'], ['records.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('record_sources', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_record_sources_record_id'), ['record_id'], unique=False)

    op.create_table('enrichment_salaries',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('enrichment_id', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('min_amount', sa.Float(), nullable=True),
    sa.Column('max_amount', sa.Float(), nullable=True),
    sa.Column('currency', sa.Text(), nullable=False),
    sa.Column('period', sa.Text(), nullable=False),
    sa.Column('location', sa.Text(), nullable=True),
    sa.Column('basis', sa.Text(), nullable=False),
    sa.Column('quote', sa.Text(), nullable=False),
    sa.Column('start_offset', sa.Integer(), nullable=True),
    sa.Column('end_offset', sa.Integer(), nullable=True),
    sa.Column('verified', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['enrichment_id'], ['posting_enrichments.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('enrichment_salaries', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_enrichment_salaries_enrichment_id'), ['enrichment_id'], unique=False)

    op.create_table('enrichment_skills',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('enrichment_id', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('importance', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('quote', sa.Text(), nullable=False),
    sa.Column('start_offset', sa.Integer(), nullable=True),
    sa.Column('end_offset', sa.Integer(), nullable=True),
    sa.Column('verified', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['enrichment_id'], ['posting_enrichments.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('enrichment_skills', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_enrichment_skills_enrichment_id'), ['enrichment_id'], unique=False)

    op.create_table('llm_jobs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('kind', sa.Text(), server_default='posting', nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=True),
    sa.Column('snapshot_id', sa.Integer(), nullable=True),
    sa.Column('document_id', sa.Integer(), nullable=True),
    sa.Column('model', sa.Text(), nullable=False),
    sa.Column('pipeline', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('enrichment_id', sa.Integer(), nullable=True),
    sa.Column('document_run_id', sa.Integer(), nullable=True),
    sa.Column('queued_at', UTCDateTime(), nullable=False),
    sa.Column('started_at', UTCDateTime(), nullable=True),
    sa.Column('finished_at', UTCDateTime(), nullable=True),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['document_run_id'], ['document_runs.id'], ),
    sa.ForeignKeyConstraint(['enrichment_id'], ['posting_enrichments.id'], ),
    sa.ForeignKeyConstraint(['job_id'], ['postings.job_id'], ),
    sa.ForeignKeyConstraint(['snapshot_id'], ['posting_snapshots.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('llm_jobs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_llm_jobs_job_id'), ['job_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_llm_jobs_status'), ['status'], unique=False)


    op.bulk_insert(
        sa.table("dismiss_reasons", sa.column("label"), sa.column("key"), sa.column("position")),
        [
            {"label": label, "key": key, "position": position}
            for position, (label, key) in enumerate(DEFAULT_DISMISS_REASONS, start=1)
        ],
    )


def downgrade() -> None:
    with op.batch_alter_table('llm_jobs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_llm_jobs_status'))
        batch_op.drop_index(batch_op.f('ix_llm_jobs_job_id'))

    op.drop_table('llm_jobs')
    with op.batch_alter_table('enrichment_skills', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_enrichment_skills_enrichment_id'))

    op.drop_table('enrichment_skills')
    with op.batch_alter_table('enrichment_salaries', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_enrichment_salaries_enrichment_id'))

    op.drop_table('enrichment_salaries')
    with op.batch_alter_table('record_sources', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_record_sources_record_id'))

    op.drop_table('record_sources')
    with op.batch_alter_table('record_lines', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_record_lines_record_id'))

    op.drop_table('record_lines')
    with op.batch_alter_table('posting_skill_marks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_posting_skill_marks_skill_id'))
        batch_op.drop_index(batch_op.f('ix_posting_skill_marks_job_id'))

    op.drop_table('posting_skill_marks')
    with op.batch_alter_table('posting_enrichments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_posting_enrichments_snapshot_id'))
        batch_op.drop_index(batch_op.f('ix_posting_enrichments_job_id'))

    op.drop_table('posting_enrichments')
    with op.batch_alter_table('highlight_claims', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_highlight_claims_claim_id'))

    op.drop_table('highlight_claims')
    with op.batch_alter_table('claim_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_claim_records_record_id'))

    op.drop_table('claim_records')
    with op.batch_alter_table('tailored_cv_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tailored_cv_items_cv_id'))

    op.drop_table('tailored_cv_items')
    with op.batch_alter_table('records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_records_part_of_id'))

    op.drop_table('records')
    with op.batch_alter_table('profile_suggestions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_profile_suggestions_run_id'))

    op.drop_table('profile_suggestions')
    with op.batch_alter_table('posting_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_posting_snapshots_job_id'))

    op.drop_table('posting_snapshots')
    op.drop_table('posting_dismissal_reasons')
    op.drop_table('highlights')
    with op.batch_alter_table('contact_emails', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_contact_emails_contact_id'))

    op.drop_table('contact_emails')
    op.drop_table('claims')
    with op.batch_alter_table('application_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_application_events_application_id'))

    op.drop_table('application_events')
    op.drop_table('application_documents')
    op.drop_table('application_contacts')
    with op.batch_alter_table('tailored_cvs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tailored_cvs_job_id'))

    op.drop_table('tailored_cvs')
    op.drop_table('skill_link_overrides')
    with op.batch_alter_table('skill_aliases', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_skill_aliases_skill_id'))

    op.drop_table('skill_aliases')
    op.drop_table('rejected_suggestions')
    op.drop_table('posting_triage')
    op.drop_table('posting_tags')
    with op.batch_alter_table('posting_dismissals', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_posting_dismissals_job_id'))

    op.drop_table('posting_dismissals')
    op.drop_table('link_relations')
    with op.batch_alter_table('document_runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_document_runs_document_id'))

    op.drop_table('document_runs')
    with op.batch_alter_table('contacts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_contacts_company_id'))

    op.drop_table('contacts')
    with op.batch_alter_table('captures', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_captures_job_id'))

    op.drop_table('captures')
    op.drop_table('applications')
    op.drop_table('tags')
    op.drop_table('skills')
    with op.batch_alter_table('skill_expansions', schema=None) as batch_op:
        batch_op.drop_index('ix_skill_expansions_lookup')

    op.drop_table('skill_expansions')
    op.drop_table('skill_embeddings')
    op.drop_table('profile_rejections')
    op.drop_table('profile_details')
    op.drop_table('postings')
    with op.batch_alter_table('link_measurements', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_link_measurements_posting_key'))

    op.drop_table('link_measurements')
    with op.batch_alter_table('link_judgments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_link_judgments_posting_key'))

    op.drop_table('link_judgments')
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_documents_sha256'))

    op.drop_table('documents')
    op.drop_table('dismiss_reasons')
    op.drop_table('companies')
    op.drop_table('app_settings')
