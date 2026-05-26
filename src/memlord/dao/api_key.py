import hashlib
import secrets

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from memlord.models.api_key import ApiKey
from memlord.schemas.api_key import ApiKeyCreate, ApiKeyInfo
from memlord.utils.dt import utcnow

MAX_KEYS_PER_USER = 5


def _generate_raw_key() -> str:
    return "mlk_" + secrets.token_urlsafe(32)


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class ApiKeyDao:
    def __init__(self, s: AsyncSession) -> None:
        self._s = s

    async def create(self, user_id: int, data: ApiKeyCreate) -> tuple[str, ApiKeyInfo]:
        """Create an API key. Returns (raw_key, key_info)."""
        count = await self._s.scalar(
            select(func.count()).select_from(ApiKey).where(ApiKey.user_id == user_id)
        )
        assert count is not None
        if count >= MAX_KEYS_PER_USER:
            raise ValueError(f"Maximum {MAX_KEYS_PER_USER} API keys per user")

        raw_key = _generate_raw_key()
        key_hash = _hash_key(raw_key)
        prefix = raw_key[:12]

        key_id = await self._s.scalar(
            insert(ApiKey)
            .values(
                user_id=user_id,
                name=data.name,
                key_hash=key_hash,
                prefix=prefix,
            )
            .returning(ApiKey.id)
        )
        assert key_id is not None

        now = utcnow()
        return raw_key, ApiKeyInfo(
            id=key_id,
            name=data.name,
            prefix=prefix,
            created_at=now,
            last_used_at=None,
        )

    async def list_by_user(self, user_id: int) -> list[ApiKeyInfo]:
        rows = (
            (
                await self._s.execute(
                    select(
                        ApiKey.id,
                        ApiKey.name,
                        ApiKey.prefix,
                        ApiKey.created_at,
                        ApiKey.last_used_at,
                    )
                    .where(ApiKey.user_id == user_id)
                    .order_by(ApiKey.created_at.desc())
                )
            )
            .mappings()
            .all()
        )
        return [ApiKeyInfo(**dict(row)) for row in rows]

    async def delete(self, user_id: int, key_id: int) -> bool:
        result = await self._s.execute(
            delete(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user_id)
        )
        return result.rowcount > 0  # type: ignore[union-attr]

    async def validate_key(self, raw_key: str) -> tuple[int, int] | None:
        """Validate an API key. Returns (key_id, user_id) or None."""
        key_hash = _hash_key(raw_key)
        row = (
            (
                await self._s.execute(
                    select(ApiKey.id, ApiKey.user_id).where(ApiKey.key_hash == key_hash)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return row["id"], row["user_id"]

    async def touch_last_used(self, key_id: int) -> None:
        await self._s.execute(
            update(ApiKey).where(ApiKey.id == key_id).values(
                last_used_at=utcnow()
            )
        )
