"""init schema"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signal",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("device_id", sa.String(length=64), index=True),
        sa.Column("payload", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "auditlog",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("device_id", sa.String(length=64), index=True),
        sa.Column("threat_level", sa.String(length=32)),
        sa.Column("reason", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("signal_id", sa.Integer, sa.ForeignKey("signal.id")),
    )


def downgrade() -> None:
    op.drop_table("auditlog")
    op.drop_table("signal")
