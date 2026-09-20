import base64
import hashlib
import hmac
import secrets
_SALT_BYTES = 16
_KEY_BYTES = 32


def _validate_password(password: str) -> None:
    from app.config import settings
    if not isinstance(password, str) or not (settings.AUTH_PASSWORD_MIN_LENGTH <= len(password) <= settings.AUTH_PASSWORD_MAX_LENGTH):
        raise ValueError("invalid_password")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    if not value or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for ch in value):
        raise ValueError
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    _validate_password(password)
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=_KEY_BYTES)
    return f"scrypt$16384$8$1${_encode(salt)}${_encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _validate_password(password)
        if not isinstance(encoded, str):
            return False
        scheme, n_text, r_text, p_text, salt_text, digest_text = encoded.split("$")
        if scheme != "scrypt" or (n_text, r_text, p_text) != ("16384", "8", "1"):
            return False
        salt = _decode(salt_text)
        expected = _decode(digest_text)
        if len(salt) != _SALT_BYTES or len(expected) != _KEY_BYTES:
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=_KEY_BYTES)
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError, UnicodeError):
        return False


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
