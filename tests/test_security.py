import pytest
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
import jwt

from src.auth.security import SecurityUtils


class TestPasswordHashing:
    def test_hash_password_returns_different_hash(self):
        plain = "TestPassword123"
        hash1 = SecurityUtils.hash_password(plain)
        hash2 = SecurityUtils.hash_password(plain)
        assert hash1 != hash2, "Hashes should be different due to salt"

    def test_verify_password_correct_returns_true(self):
        plain = "TestPassword123"
        hashed = SecurityUtils.hash_password(plain)
        assert SecurityUtils.verify_password(plain, hashed) is True

    def test_verify_password_wrong_returns_false(self):
        hashed = SecurityUtils.hash_password("CorrectPassword")
        assert SecurityUtils.verify_password("WrongPassword", hashed) is False

    def test_hash_verify_round_trip(self):
        passwords = ["short", "a" * 100, "SpecialChars!@#$%", "unicode_café_测试"]
        for plain in passwords:
            hashed = SecurityUtils.hash_password(plain)
            assert SecurityUtils.verify_password(plain, hashed) is True


class TestJWT:
    def test_create_jwt_token_returns_string(self):
        data = {"sub": "user-123", "email": "test@example.com"}
        token = SecurityUtils.create_jwt_token(data)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_decode_jwt_token_returns_payload(self):
        data = {"sub": "user-123", "email": "test@example.com"}
        token = SecurityUtils.create_jwt_token(data)
        decoded = SecurityUtils.decode_jwt_token(token)
        assert decoded["sub"] == "user-123"
        assert decoded["email"] == "test@example.com"

    def test_decode_jwt_token_expired_raises_401(self):
        past_time = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())
        token = jwt.encode(
            {"sub": "user-123", "exp": past_time},
            SecurityUtils.JWT_SECRET,
            algorithm=SecurityUtils.JWT_ALGORITHM,
        )
        with pytest.raises(HTTPException) as exc_info:
            SecurityUtils.decode_jwt_token(token)
        assert exc_info.value.status_code == 401

    def test_decode_jwt_token_tampered_raises_401(self):
        data = {"sub": "user-123"}
        token = SecurityUtils.create_jwt_token(data)
        tampered_token = token[:-10] + "tampered!!"
        with pytest.raises(HTTPException) as exc_info:
            SecurityUtils.decode_jwt_token(tampered_token)
        assert exc_info.value.status_code == 401

    def test_decode_jwt_token_wrong_secret_raises_401(self):
        token = jwt.encode(
            {"sub": "user-123"},
            "a-different-secret-that-is-at-least-32-chars",
            algorithm="HS256",
        )
        with pytest.raises(HTTPException) as exc_info:
            SecurityUtils.decode_jwt_token(token)
        assert exc_info.value.status_code == 401

    def test_decode_rejects_unsigned_alg_none_token(self):
        token = jwt.encode({"sub": "user-123"}, key=None, algorithm="none")
        with pytest.raises(HTTPException) as exc_info:
            SecurityUtils.decode_jwt_token(token)
        assert exc_info.value.status_code == 401

    @pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")
    def test_decode_rejects_other_hmac_algorithms_even_with_the_real_secret(self):
        """Only HS256 is accepted — the algorithm list is pinned, so a token
        can't pick its own algorithm (the class of bug behind python-jose's
        algorithm-confusion advisory)."""
        token = jwt.encode({"sub": "user-123"}, SecurityUtils.JWT_SECRET, algorithm="HS512")
        with pytest.raises(HTTPException) as exc_info:
            SecurityUtils.decode_jwt_token(token)
        assert exc_info.value.status_code == 401

    def test_decode_jwt_token_invalid_format_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            SecurityUtils.decode_jwt_token("not-a-valid-jwt")
        assert exc_info.value.status_code == 401
