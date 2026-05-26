import sqlalchemy as sa

from .base import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    user_id = sa.Column(sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = sa.Column(sa.String(100), nullable=False)
    key_hash = sa.Column(sa.String(64), nullable=False)
    prefix = sa.Column(sa.String(12), nullable=False)
    created_at = sa.Column(sa.DateTime, server_default=sa.func.now(), nullable=False)
    last_used_at = sa.Column(sa.DateTime, nullable=True)
