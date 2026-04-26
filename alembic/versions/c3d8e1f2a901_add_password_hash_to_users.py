"""add password_hash to users

Revision ID: c3d8e1f2a901
Revises: b7c9f2a3e854
Create Date: 2026-04-26 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c3d8e1f2a901'
down_revision: Union[str, None] = 'b7c9f2a3e854'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('password_hash', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'password_hash')
