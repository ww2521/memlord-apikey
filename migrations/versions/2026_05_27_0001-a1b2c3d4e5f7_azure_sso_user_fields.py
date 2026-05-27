"""azure sso user fields

Revision ID: a1b2c3d4e5f7
Revises: 7e2e8e52e1c5439a
Create Date: 2026-05-27

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, Sequence[str], None] = "7e2e8e52e1c5439a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("azure_sub", sa.String(255), unique=True, nullable=True))
    op.add_column("users", sa.Column("auth_method", sa.String(32), server_default="local", nullable=False))
    op.alter_column("users", "hashed_password", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.alter_column("users", "hashed_password", existing_type=sa.Text(), nullable=False)
    op.drop_column("users", "auth_method")
    op.drop_column("users", "azure_sub")
