"""Hashing and encryption primitives."""
import base64
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet

from app.core.config import get_settings

# Argon2id (argon2-cffi default type is ID). Parameters follow OWASP guidance.
_ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16)
# Cheaper Argon2id instance for short-lived OTPs/backup codes (still salted + memory-hard).
_otp_ph = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)

# Constant dummy hash used to equalise timing when the account does not exist.
_DUMMY_HASH = _ph.hash("astitva-timing-equaliser-not-a-password")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _ph.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _ph.check_needs_rehash(password_hash)


def hash_otp(code: str) -> str:
    return _otp_ph.hash(code)


def verify_otp(code_hash: str | None, code: str) -> bool:
    if not code_hash:
        return False
    try:
        return _otp_ph.verify(code_hash, code)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def token_digest(token: str) -> str:
    """Keyed SHA-256 for high-entropy bearer secrets (refresh/access tokens, agent keys)."""
    key = get_settings().token_pepper.encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


def random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def numeric_code(digits: int = 6) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(digits))


def _fernet() -> Fernet:
    key = hashlib.sha256(("fernet:" + get_settings().token_pepper).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()
