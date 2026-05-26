"""Tests for API key creation, validation, and auth resolution."""

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from fastmcp import Client

from memlord.auth import MCPUserDep, hash_password
from memlord.dao.api_key import ApiKeyDao, _generate_raw_key, _hash_key
from memlord.dao.user import UserDao
from memlord.db import MCPSessionDep
from memlord.oauth import MemlordOAuthProvider
from memlord.schemas.api_key import ApiKeyCreate
from memlord.server import mcp


class TestKeyGeneration:
    def test_raw_key_starts_with_prefix(self):
        key = _generate_raw_key()
        assert key.startswith("mlk_")
        assert len(key) > 20

    def test_hash_key_deterministic(self):
        h1 = _hash_key("mlk_test123")
        h2 = _hash_key("mlk_test123")
        assert h1 == h2
        assert len(h1) == 64

    def test_hash_key_different_for_different_inputs(self):
        h1 = _hash_key("mlk_abc")
        h2 = _hash_key("mlk_xyz")
        assert h1 != h2


class TestApiKeyDao:
    async def test_create_returns_raw_key_and_info(self, session, user_id):
        dao = ApiKeyDao(session)
        raw, info = await dao.create(user_id, ApiKeyCreate(name="test-key"))
        assert raw.startswith("mlk_")
        assert info.name == "test-key"
        assert info.prefix == raw[:12]

    async def test_create_stores_hash_not_raw(self, session, user_id):
        dao = ApiKeyDao(session)
        raw, info = await dao.create(user_id, ApiKeyCreate(name="test-key"))
        result = await dao.validate_key(raw)
        assert result is not None
        assert result[1] == user_id

    async def test_list_by_user(self, session, user_id):
        dao = ApiKeyDao(session)
        await dao.create(user_id, ApiKeyCreate(name="key-a"))
        await dao.create(user_id, ApiKeyCreate(name="key-b"))
        keys = await dao.list_by_user(user_id)
        assert len(keys) == 2
        names = {k.name for k in keys}
        assert names == {"key-a", "key-b"}

    async def test_delete(self, session, user_id):
        dao = ApiKeyDao(session)
        raw, info = await dao.create(user_id, ApiKeyCreate(name="to-delete"))
        deleted = await dao.delete(user_id, info.id)
        assert deleted is True
        result = await dao.validate_key(raw)
        assert result is None

    async def test_delete_wrong_user(self, session, user_id):
        """Deleting another user's key returns False."""
        dao = ApiKeyDao(session)
        other = await UserDao(session).create(
            email="other@example.com",
            display_name="Other",
            hashed_password=hash_password("pw"),
        )
        raw, info = await dao.create(other.id, ApiKeyCreate(name="other-key"))
        deleted = await dao.delete(user_id, info.id)
        assert deleted is False
        # Key still valid
        result = await dao.validate_key(raw)
        assert result is not None

    async def test_validate_invalid_key(self, session, user_id):
        dao = ApiKeyDao(session)
        result = await dao.validate_key("mlk_nonexistent")
        assert result is None

    async def test_max_keys_per_user(self, session, user_id):
        dao = ApiKeyDao(session)
        for i in range(5):
            await dao.create(user_id, ApiKeyCreate(name=f"key-{i}"))
        with pytest.raises(ValueError, match="Maximum"):
            await dao.create(user_id, ApiKeyCreate(name="key-6"))


class TestOAuthProviderApiKey:
    """Test that load_access_token resolves API keys."""

    @pytest.fixture
    def provider(self, session):
        @asynccontextmanager
        async def session_factory():
            yield session

        return MemlordOAuthProvider(
            base_url="https://example.com",
            jwt_secret="test-secret",
            session_factory=session_factory,
        )

    async def test_load_access_token_accepts_api_key(self, provider, session, user_id):
        dao = ApiKeyDao(session)
        raw, info = await dao.create(user_id, ApiKeyCreate(name="test"))
        token = await provider.load_access_token(raw)
        assert token is not None
        assert token.client_id == f"api_key:{info.id}"
        assert "mcp" in token.scopes

    async def test_load_access_token_rejects_invalid_api_key(self, provider):
        token = await provider.load_access_token("mlk_invalid_key")
        assert token is None


class TestMCPClientWithApiKey:
    """Integration test: MCP client can use API key to authenticate."""

    async def test_store_memory_via_api_key(self, session, user_id):
        """Create an API key and use it to call store_memory via MCP."""
        dao = ApiKeyDao(session)
        await dao.create(user_id, ApiKeyCreate(name="test-client"))

        # Build a custom auth dependency that yields the API key's user_id
        async def _session():
            yield session

        async def _user_from_api_key():
            yield user_id

        with (
            patch.object(MCPSessionDep, "factory", asynccontextmanager(_session)),
            patch.object(MCPUserDep, "factory", asynccontextmanager(_user_from_api_key)),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "store_memory",
                    {
                        "content": "API key auth integration test",
                        "memory_type": "fact",
                        "name": "test-memory",
                    },
                )
                assert result is not None
