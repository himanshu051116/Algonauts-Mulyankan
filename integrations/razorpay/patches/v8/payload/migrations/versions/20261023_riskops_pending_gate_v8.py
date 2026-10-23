"""Prevent any second provider operation while a case has an unresolved outcome.

Revision ID: 20261023_riskops_pending_v8
Revises: 20261023_riskops_ops_v7

Run only after ALL v7 workers have been drained and the v7 migration applied.
"""
from alembic import op
import sqlalchemy as sa

revision = '20261023_riskops_pending_v8'
down_revision = '20261023_riskops_ops_v7'
branch_labels = None
depends_on = None

PENDING = "status IN ('reserved', 'observed', 'ambiguous')"


def upgrade() -> None:
    # A pre-existing v7 database may contain two outstanding provider intents
    # for one case. Never discard/auto-complete these forensic records.
    duplicate = op.get_bind().execute(sa.text("""
        SELECT case_id, count(*) AS attempts
        FROM riskops_provider_operations
        WHERE status IN ('reserved', 'observed', 'ambiguous')
        GROUP BY case_id HAVING count(*) > 1 LIMIT 1
    """)).first()
    if duplicate is not None:
        raise RuntimeError(
            'Cannot enable RiskOps case-wide pending gate: multiple unresolved '
            'operations already exist. Investigate and coordinate a manual '
            'incident repair; never drop journal rows to pass this check.'
        )
    op.create_index('uq_riskops_one_pending_per_case',
                    'riskops_provider_operations', ['case_id'], unique=True,
                    postgresql_where=sa.text(PENDING))


def downgrade() -> None:
    raise RuntimeError(
        'Security-sensitive downgrade refused: dropping the case-wide pending '
        'gate could permit duplicate Razorpay effects. Use a reviewed manual rollback.'
    )
