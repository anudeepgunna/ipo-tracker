"""Google sign-in fields and recurring reminder cadences

Revision ID: b1c2d3e4f5a6
Revises: d3e997a368f6
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "d3e997a368f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_RULE_TYPES = ("DAILY_UNTIL_CLOSE", "DAY_BEFORE_CLOSE")


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("avatar_url", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("google_sub", sa.String(length=64), nullable=True))
    op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)

    # Postgres stores RuleType as a native enum, so new members must be added to
    # the type itself. SQLite (used by the test suite) has no enum type at all
    # and needs nothing here.
    if op.get_bind().dialect.name == "postgresql":
        for value in _NEW_RULE_TYPES:
            op.execute(f"ALTER TYPE ruletype ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    op.drop_index("ix_users_google_sub", table_name="users")
    op.drop_column("users", "google_sub")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "display_name")
    # Postgres cannot remove a value from an enum type; rebuilding it would mean
    # rewriting every dependent column, so the added members are left in place.
    # They are inert unless a rule references them.
