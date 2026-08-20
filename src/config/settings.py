import os
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings


class BaseAppSettings(BaseSettings):

    BASE_DIR: Path = Path(__file__).parent.parent
    PATH_TO_DB: str = str(BASE_DIR / "database" / "source" / "cinema.db")

    ACTIVATION_TOKEN_TTL_HOURS: int = 24
    PASSWORD_RESET_TOKEN_TTL_HOURS: int = 1
    LOGIN_TIME_DAYS: int = 7

    PATH_TO_EMAIL_TEMPLATES_DIR: str = str(BASE_DIR / "notifications" / "templates")
    ACTIVATION_EMAIL_TEMPLATE_NAME: str = "activation_request.html"
    ACTIVATION_COMPLETE_EMAIL_TEMPLATE_NAME: str = "activation_complete.html"
    PASSWORD_RESET_TEMPLATE_NAME: str = "password_reset_request.html"
    PASSWORD_RESET_COMPLETE_TEMPLATE_NAME: str = "password_reset_complete.html"
    ORDER_CONFIRMATION_TEMPLATE_NAME: str = "order_confirmation.html"

    EMAIL_HOST: str = os.getenv("EMAIL_HOST", "localhost")
    EMAIL_PORT: int = int(os.getenv("EMAIL_PORT", 1025))
    EMAIL_HOST_USER: str = os.getenv("EMAIL_HOST_USER", "cinema")
    EMAIL_HOST_PASSWORD: str = os.getenv("EMAIL_HOST_PASSWORD", "cinema")
    EMAIL_USE_TLS: bool = os.getenv("EMAIL_USE_TLS", "False").lower() == "true"

    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    BASE_FRONTEND_URL: str = os.getenv("BASE_FRONTEND_URL", "http://127.0.0.1")

    DOCS_USERNAME: str = os.getenv("DOCS_USERNAME", "docs")
    DOCS_PASSWORD: str = os.getenv("DOCS_PASSWORD", "docs")

    SECRET_KEY_ACCESS: str = os.getenv("SECRET_KEY_ACCESS", "insecure-access-key")
    SECRET_KEY_REFRESH: str = os.getenv("SECRET_KEY_REFRESH", "insecure-refresh-key")
    JWT_SIGNING_ALGORITHM: str = os.getenv("JWT_SIGNING_ALGORITHM", "HS256")


class Settings(BaseAppSettings):

    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "cinema_user")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "cinema_password")
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_DB_PORT: int = int(os.getenv("POSTGRES_DB_PORT", 5432))
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "cinema_db")

    SECRET_KEY_ACCESS: str = os.getenv("SECRET_KEY_ACCESS", os.urandom(32).hex())
    SECRET_KEY_REFRESH: str = os.getenv("SECRET_KEY_REFRESH", os.urandom(32).hex())


class TestingSettings(BaseAppSettings):

    SECRET_KEY_ACCESS: str = "test-secret-key-access"
    SECRET_KEY_REFRESH: str = "test-secret-key-refresh"
    JWT_SIGNING_ALGORITHM: str = "HS256"

    def model_post_init(self, __context: dict[str, Any] | None = None) -> None:
        object.__setattr__(self, "PATH_TO_DB", ":memory:")
