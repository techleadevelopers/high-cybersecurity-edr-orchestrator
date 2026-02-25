"""subscription tables"""
from alembic import op
import sqlalchemy as sa
import datetime as dt
import uuid

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan",
        sa.Column("id", sa.String(length=36), primary_key=True, default=lambda: str(uuid.uuid4())),
        sa.Column("code", sa.String(length=32), unique=True, index=True),
        sa.Column("name", sa.String(length=64)),
        sa.Column("price_cents", sa.Integer()),
        sa.Column("currency", sa.String(length=8), server_default="BRL"),
        sa.Column("features", sa.JSON(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "subscription",
        sa.Column("id", sa.String(length=36), primary_key=True, default=lambda: str(uuid.uuid4())),
        sa.Column("user_id", sa.String(length=64), index=True),
        sa.Column("device_id", sa.String(length=64), index=True),
        sa.Column("plan_code", sa.String(length=32)),
        sa.Column("status", sa.String(length=16), server_default="trial"),
        sa.Column("plan_tier", sa.String(length=16), server_default="trial"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "billingevent",
        sa.Column("id", sa.String(length=36), primary_key=True, default=lambda: str(uuid.uuid4())),
        sa.Column("provider", sa.String(length=32)),
        sa.Column("event_id", sa.String(length=128), unique=True, index=True),
        sa.Column("payload", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("billingevent")
    op.drop_table("subscription")
    op.drop_table("plan")
