import sqlalchemy as sa

from .base import Base


class User(Base):
    __tablename__ = "users"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    email = sa.Column(sa.Text, unique=True, nullable=False)
    display_name = sa.Column(sa.Text, nullable=False, server_default="")
    hashed_password = sa.Column(sa.Text, nullable=True)
    email_verified = sa.Column(sa.Boolean, nullable=False, server_default=sa.false())
    azure_sub = sa.Column(sa.String(255), unique=True, nullable=True)
    auth_method = sa.Column(sa.String(32), nullable=False, server_default="local")
    created_at = sa.Column(
        sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False
    )
