"""Moderated vacancies and candidate applications with immutable transition history."""

import sqlalchemy as sa
from alembic import context, op

revision = "0005_hiring"
down_revision = "0004_hiring"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hiring_vacancies",
        sa.Column("vacancy_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("need_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("organization_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("created_by", sa.String(36), nullable=False, primary_key=False),
        sa.Column("spec", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("status", sa.String(16), nullable=False, primary_key=False),
        sa.Column("revision", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.UniqueConstraint("need_id"),
    )
    op.create_index("ix_hiring_vacancies_created_by", "hiring_vacancies", ["created_by"])
    op.create_index("ix_hiring_vacancies_organization_id", "hiring_vacancies", ["organization_id"])
    op.create_table(
        "hiring_vacancy_decisions",
        sa.Column("decision_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("vacancy_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("reviewer_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("revision", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("outcome", sa.String(16), nullable=False, primary_key=False),
        sa.Column("reason", sa.String(2000), nullable=False, primary_key=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.UniqueConstraint("vacancy_id", "revision"),
    )
    op.create_index(
        "ix_hiring_vacancy_decisions_reviewer_id", "hiring_vacancy_decisions", ["reviewer_id"]
    )
    op.create_index(
        "ix_hiring_vacancy_decisions_vacancy_id", "hiring_vacancy_decisions", ["vacancy_id"]
    )
    op.create_table(
        "hiring_applications",
        sa.Column("application_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("vacancy_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("organization_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("created_by", sa.String(36), nullable=False, primary_key=False),
        sa.Column("candidate_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("vacancy_version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("vacancy_snapshot", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("invitation_id", sa.String(36), nullable=True, primary_key=False),
        sa.Column("status", sa.String(16), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.UniqueConstraint("vacancy_id", "candidate_id"),
        sa.UniqueConstraint("invitation_id"),
    )
    op.create_index("ix_hiring_applications_candidate_id", "hiring_applications", ["candidate_id"])
    op.create_index("ix_hiring_applications_created_by", "hiring_applications", ["created_by"])
    op.create_index(
        "ix_hiring_applications_organization_id", "hiring_applications", ["organization_id"]
    )
    op.create_index("ix_hiring_applications_vacancy_id", "hiring_applications", ["vacancy_id"])
    op.create_table(
        "hiring_application_changes",
        sa.Column("change_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("application_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("actor_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("status", sa.String(16), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.UniqueConstraint("application_id", "version"),
    )
    op.create_index(
        "ix_hiring_application_changes_actor_id", "hiring_application_changes", ["actor_id"]
    )
    op.create_index(
        "ix_hiring_application_changes_application_id",
        "hiring_application_changes",
        ["application_id"],
    )
    with op.batch_alter_table("hiring_notices") as batch:
        batch.alter_column("invitation_id", existing_type=sa.String(36), nullable=True)
        batch.add_column(sa.Column("application_id", sa.String(36), nullable=True))
        batch.create_index("ix_hiring_notices_application_id", ["application_id"])


def downgrade():
    bind = op.get_bind()
    target = context.get_revision_argument()
    tables = [
        "hiring_vacancies",
        "hiring_vacancy_decisions",
        "hiring_applications",
        "hiring_application_changes",
    ]
    if target != "0004_hiring":
        tables += ["hiring_complaint_cases", "hiring_complaint_decisions"]
    if target not in {"0004_hiring", "0003_hiring"}:
        tables += [
            "hiring_dialogs",
            "hiring_messages",
            "hiring_employer_blocks",
            "hiring_complaints",
            "hiring_notices",
        ]
    if target not in {"0004_hiring", "0003_hiring", "0002_hiring"}:
        tables += ["hiring_needs", "hiring_invitations", "hiring_market_nonces"]
    for table in tables:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated vacancy/application data")
    if bind.execute(
        sa.text("SELECT 1 FROM hiring_notices WHERE application_id IS NOT NULL LIMIT 1")
    ).first():
        raise RuntimeError("Cannot downgrade populated vacancy/application data")
    if (
        target not in {"0004_hiring", "0003_hiring", "0002_hiring"}
        and bind.execute(
            sa.text("SELECT 1 FROM hiring_subjects WHERE blocked = true LIMIT 1")
        ).first()
    ):
        raise RuntimeError("Cannot downgrade populated vacancy/application data")
    with op.batch_alter_table("hiring_notices") as batch:
        batch.drop_index("ix_hiring_notices_application_id")
        batch.drop_column("application_id")
        batch.alter_column("invitation_id", existing_type=sa.String(36), nullable=False)
    op.drop_table("hiring_application_changes")
    op.drop_table("hiring_applications")
    op.drop_table("hiring_vacancy_decisions")
    op.drop_table("hiring_vacancies")
