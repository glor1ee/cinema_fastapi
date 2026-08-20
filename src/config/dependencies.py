import os

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from config.settings import BaseAppSettings, Settings, TestingSettings
from database import UserGroupEnum, UserModel, get_db
from exceptions import BaseSecurityError
from notifications import EmailSender
from security.http import get_token
from security.token_manager import JWTAuthManager


def get_settings() -> BaseAppSettings:
    if os.getenv("ENVIRONMENT", "developing") == "testing":
        return TestingSettings()
    return Settings()


def get_jwt_auth_manager(
    settings: BaseAppSettings = Depends(get_settings),
) -> JWTAuthManager:
    return JWTAuthManager(
        secret_key_access=settings.SECRET_KEY_ACCESS,
        secret_key_refresh=settings.SECRET_KEY_REFRESH,
        algorithm=settings.JWT_SIGNING_ALGORITHM,
    )


def get_accounts_email_notificator(
    settings: BaseAppSettings = Depends(get_settings),
) -> EmailSender:
    return EmailSender(
        hostname=settings.EMAIL_HOST,
        port=settings.EMAIL_PORT,
        email=settings.EMAIL_HOST_USER,
        password=settings.EMAIL_HOST_PASSWORD,
        use_tls=settings.EMAIL_USE_TLS,
        template_dir=settings.PATH_TO_EMAIL_TEMPLATES_DIR,
        activation_email_template_name=settings.ACTIVATION_EMAIL_TEMPLATE_NAME,
        activation_complete_email_template_name=(settings.ACTIVATION_COMPLETE_EMAIL_TEMPLATE_NAME),
        password_email_template_name=settings.PASSWORD_RESET_TEMPLATE_NAME,
        password_complete_email_template_name=settings.PASSWORD_RESET_COMPLETE_TEMPLATE_NAME,
    )


async def get_current_user(
    token: str = Depends(get_token),
    db: AsyncSession = Depends(get_db),
    jwt_manager: JWTAuthManager = Depends(get_jwt_auth_manager),
) -> UserModel:
    try:
        payload = jwt_manager.decode_access_token(token)
    except BaseSecurityError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error

    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload."
        )

    user = await db.get(UserModel, user_id, options=[joinedload(UserModel.group)])
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or not active.",
        )

    return user


async def require_moderator(current_user: UserModel = Depends(get_current_user)) -> UserModel:
    if current_user.group.name not in (UserGroupEnum.MODERATOR, UserGroupEnum.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )
    return current_user


async def require_admin(current_user: UserModel = Depends(get_current_user)) -> UserModel:
    if current_user.group.name != UserGroupEnum.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )
    return current_user
