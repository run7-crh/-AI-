import base64
import hashlib

import pytest
from pydantic import ValidationError

from app.models.auth import Credentials, UserPublic
from app.services.auth_store import hash_password, hash_session_token, verify_password


def test_password_hash_round_trip_and_scrypt_format():
    encoded = hash_password("correct horse")
    parts = encoded.split("$")
    assert parts[0] == "scrypt"
    assert len(parts) == 6
    assert parts[1:4] == ["16384", "8", "1"]
    assert verify_password("correct horse", encoded)
    assert not verify_password("wrong", encoded)
    assert len(base64.urlsafe_b64decode(parts[4] + "===")) == 16
    assert len(base64.urlsafe_b64decode(parts[5] + "===")) == 32


def test_password_validation_and_malformed_hashes():
    with pytest.raises(ValueError, match="invalid_password"):
        hash_password("short")
    with pytest.raises(ValueError, match="invalid_password"):
        hash_password("x" * 129)
    assert not verify_password("password", "scrypt$16384$8$1$not-base64$bad")
    assert not verify_password("password", "not-a-hash")
    assert not verify_password("password", None)
    assert not verify_password("password", b"scrypt$16384$8$1$bad$bad")


def test_password_limits_follow_current_settings(monkeypatch):
    import app.config as config
    monkeypatch.setattr(config, "settings", config.Settings(DEEPSEEK_API_KEY="x", TAVILY_API_KEY="x", AUTH_PASSWORD_MIN_LENGTH=3, AUTH_PASSWORD_MAX_LENGTH=4))
    assert hash_password("abc")
    with pytest.raises(ValueError, match="invalid_password"):
        hash_password("ab")
    with pytest.raises(ValueError, match="invalid_password"):
        hash_password("abcde")


def test_session_token_is_sha256_hex_digest():
    token = "opaque-token"
    assert hash_session_token(token) == hashlib.sha256(token.encode()).hexdigest()


def test_auth_models_validate_fields():
    user = UserPublic(id="u1", username="alice", role="user", is_active=True, created_at="2026-01-01T00:00:00Z")
    assert user.username == "alice"
    with pytest.raises(ValidationError):
        Credentials(username="", password="x")
    with pytest.raises(ValidationError):
        Credentials(username="alice", password="x" * 129)
