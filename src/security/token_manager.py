from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import ExpiredSignatureError, JWTError, jwt

from exceptions import InvalidTokenError, TokenExpiredError


class JWTAuthManager:

    ACCESS_TOKEN_MINUTES = 30
    REFRESH_TOKEN_MINUTES = 60 * 24 * 7

    def __init__(self, secret_key_access: str, secret_key_refresh: str, algorithm: str) -> None:
        self._secret_key_access = secret_key_access
        self._secret_key_refresh = secret_key_refresh
        self._algorithm = algorithm

    def _create_token(self, data: dict, secret_key: str, expires_delta: timedelta) -> str:
        payload = data.copy()
        payload.update({"exp": datetime.now(timezone.utc) + expires_delta})
        return jwt.encode(payload, secret_key, algorithm=self._algorithm)

    def _decode_token(self, token: str, secret_key: str) -> dict:
        try:
            return jwt.decode(token, secret_key, algorithms=[self._algorithm])
        except ExpiredSignatureError as error:
            raise TokenExpiredError() from error
        except JWTError as error:
            raise InvalidTokenError() from error

    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None) -> str:
        return self._create_token(
            data,
            self._secret_key_access,
            expires_delta or timedelta(minutes=self.ACCESS_TOKEN_MINUTES),
        )

    def create_refresh_token(self, data: dict, expires_delta: Optional[timedelta] = None) -> str:
        return self._create_token(
            data,
            self._secret_key_refresh,
            expires_delta or timedelta(minutes=self.REFRESH_TOKEN_MINUTES),
        )

    def decode_access_token(self, token: str) -> dict:
        return self._decode_token(token, self._secret_key_access)

    def decode_refresh_token(self, token: str) -> dict:
        return self._decode_token(token, self._secret_key_refresh)
