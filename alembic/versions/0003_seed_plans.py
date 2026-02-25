"""seed plans"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO plan (id, code, name, price_cents, currency, features) "
            "VALUES (:id1, :code1, :name1, :price1, 'BRL', :feat1),"
            "(:id2, :code2, :name2, :price2, 'BRL', :feat2) "
            "ON CONFLICT (code) DO NOTHING"
        ),
        params={
            "id1": "00000000-0000-0000-0000-000000000001",
            "code1": "trial",
            "name1": "Trial 14d",
            "price1": 0,
            "feat1": {"kill_switch": True, "rate_limit": 120, "window": 60},
            "id2": "00000000-0000-0000-0000-000000000002",
            "code2": "paid_basic",
            "name2": "Paid Basic",
            "price2": 990,
            "feat2": {"kill_switch": True, "rate_limit": 600, "window": 60},
        },
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM plan WHERE code IN ('trial','paid_basic')"))
