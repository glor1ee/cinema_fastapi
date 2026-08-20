from datetime import datetime, timezone
from typing import cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from config import (
    BaseAppSettings,
    get_accounts_email_notificator,
    get_current_user,
    get_jwt_auth_manager,
    get_settings,
    require_admin,
)
from database import (
    ActivationTokenModel,
    PasswordResetTokenModel,
    RefreshTokenModel,
    UserGroupEnum,
    UserGroupModel,
    UserModel,
    get_db,
)
from exceptions import BaseSecurityError
from notifications import EmailSender
from schemas.accounts import (
    LogoutRequestSchema,
    MessageResponseSchema,
    PasswordChangeRequestSchema,
    PasswordResetCompleteRequestSchema,
    PasswordResetRequestSchema,
    ResendActivationRequestSchema,
    TokenRefreshRequestSchema,
    TokenRefreshResponseSchema,
    UserActivationRequestSchema,
    UserDetailSchema,
    UserGroupUpdateRequestSchema,
    UserLoginRequestSchema,
    UserLoginResponseSchema,
    UserRegistrationRequestSchema,
    UserRegistrationResponseSchema,
)
from security.token_manager import JWTAuthManager

router = APIRouter()

GENERIC_RESET_MESSAGE = "If you are registered, you will receive an email with instructions."


def _is_expired(expires_at: datetime) -> bool:
    aware = cast(datetime, expires_at).replace(tzinfo=timezone.utc)
    return aware < datetime.now(timezone.utc)


@router.post(
    "/register/",
    response_model=UserRegistrationResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description=(
        "Creates an account in the `user` group and emails an activation link "
        "that stays valid for 24 hours. The account cannot sign in until it is "
        "activated."
    ),
    responses={
        409: {"description": "A user with this email already exists."},
        500: {"description": "The account could not be created."},
    },
)
async def register_user(
    user_data: UserRegistrationRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSender = Depends(get_accounts_email_notificator),
    settings: BaseAppSettings = Depends(get_settings),
) -> UserRegistrationResponseSchema:
    existing = await db.execute(select(UserModel).where(UserModel.email == user_data.email))
    if existing.scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with this email {user_data.email} already exists.",
        )

    group_result = await db.execute(
        select(UserGroupModel).where(UserGroupModel.name == UserGroupEnum.USER)
    )
    user_group = group_result.scalars().first()
    if user_group is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Default user group is missing.",
        )

    try:
        new_user = UserModel.create(
            email=str(user_data.email),
            raw_password=user_data.password,
            group_id=user_group.id,
        )
        db.add(new_user)
        await db.flush()

        activation_token = ActivationTokenModel.create(
            user_id=new_user.id, hours_valid=settings.ACTIVATION_TOKEN_TTL_HOURS
        )
        db.add(activation_token)
        await db.commit()
        await db.refresh(new_user)
    except SQLAlchemyError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during user creation.",
        ) from error

    activation_link = (
        f"{settings.BASE_FRONTEND_URL}/accounts/activate/"
        f"?email={new_user.email}&token={activation_token.token}"
    )
    background_tasks.add_task(email_sender.send_activation_email, new_user.email, activation_link)

    return UserRegistrationResponseSchema.model_validate(new_user)


@router.post(
    "/activate/",
    response_model=MessageResponseSchema,
    summary="Activate an account",
    description=(
        "Confirms an account with the token from the activation email. The token "
        "is single-use and is deleted once the account becomes active."
    ),
    responses={400: {"description": "The token is invalid, expired, or already used."}},
)
async def activate_account(
    activation_data: UserActivationRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSender = Depends(get_accounts_email_notificator),
    settings: BaseAppSettings = Depends(get_settings),
) -> MessageResponseSchema:
    result = await db.execute(
        select(ActivationTokenModel)
        .options(joinedload(ActivationTokenModel.user))
        .join(UserModel)
        .where(
            UserModel.email == activation_data.email,
            ActivationTokenModel.token == activation_data.token,
        )
    )
    token_record = result.scalars().first()

    if token_record is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired activation token.",
        )

    if _is_expired(token_record.expires_at):
        await db.delete(token_record)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired activation token.",
        )

    user = token_record.user
    if user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is already active.",
        )

    user.is_active = True
    await db.delete(token_record)
    await db.commit()

    login_link = f"{settings.BASE_FRONTEND_URL}/accounts/login/"
    background_tasks.add_task(email_sender.send_activation_complete_email, user.email, login_link)

    return MessageResponseSchema(message="User account activated successfully.")


@router.post(
    "/activate/resend/",
    response_model=MessageResponseSchema,
    summary="Request a fresh activation link",
    description=(
        "Issues a new 24-hour activation token when the previous one expired. "
        "The response is identical whether or not the email is registered, so "
        "the endpoint cannot be used to discover which accounts exist."
    ),
)
async def resend_activation_token(
    data: ResendActivationRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSender = Depends(get_accounts_email_notificator),
    settings: BaseAppSettings = Depends(get_settings),
) -> MessageResponseSchema:
    generic = MessageResponseSchema(
        message="If your account needs activation, a new link has been sent."
    )

    result = await db.execute(select(UserModel).where(UserModel.email == data.email))
    user = result.scalars().first()

    if user is None or user.is_active:
        return generic

    await db.execute(delete(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id))
    activation_token = ActivationTokenModel.create(
        user_id=cast(int, user.id), hours_valid=settings.ACTIVATION_TOKEN_TTL_HOURS
    )
    db.add(activation_token)
    await db.commit()

    activation_link = (
        f"{settings.BASE_FRONTEND_URL}/accounts/activate/"
        f"?email={user.email}&token={activation_token.token}"
    )
    background_tasks.add_task(email_sender.send_activation_email, user.email, activation_link)

    return generic


@router.post(
    "/login/",
    response_model=UserLoginResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Sign in",
    description=(
        "Returns an access/refresh token pair. The refresh token is also stored "
        "server-side so that logout can revoke it."
    ),
    responses={
        401: {"description": "Wrong email or password."},
        403: {"description": "The account has not been activated."},
    },
)
async def login_user(
    login_data: UserLoginRequestSchema,
    db: AsyncSession = Depends(get_db),
    jwt_manager: JWTAuthManager = Depends(get_jwt_auth_manager),
    settings: BaseAppSettings = Depends(get_settings),
) -> UserLoginResponseSchema:
    result = await db.execute(select(UserModel).where(UserModel.email == login_data.email))
    user = result.scalars().first()

    if user is None or not user.verify_password(login_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password."
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is not activated."
        )

    access_token = jwt_manager.create_access_token({"user_id": user.id})
    refresh_token = jwt_manager.create_refresh_token({"user_id": user.id})

    try:
        db.add(
            RefreshTokenModel.create(
                user_id=cast(int, user.id),
                days_valid=settings.LOGIN_TIME_DAYS,
                token=refresh_token,
            )
        )
        await db.commit()
    except SQLAlchemyError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing the request.",
        ) from error

    return UserLoginResponseSchema(access_token=access_token, refresh_token=refresh_token)


@router.post(
    "/logout/",
    response_model=MessageResponseSchema,
    summary="Sign out",
    description=(
        "Deletes the supplied refresh token from the database. The token stops "
        "working immediately, even though its signature is still valid."
    ),
    responses={401: {"description": "The refresh token is unknown or not yours."}},
)
async def logout_user(
    data: LogoutRequestSchema,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> MessageResponseSchema:
    result = await db.execute(
        select(RefreshTokenModel).where(
            RefreshTokenModel.token == data.refresh_token,
            RefreshTokenModel.user_id == current_user.id,
        )
    )
    token_record = result.scalars().first()

    if token_record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token not found."
        )

    await db.delete(token_record)
    await db.commit()

    return MessageResponseSchema(message="Logged out successfully.")


@router.post(
    "/refresh/",
    response_model=TokenRefreshResponseSchema,
    summary="Exchange a refresh token for a new access/refresh pair",
    description=(
        "Rotates the refresh token: the one supplied here stops working the "
        "moment this call succeeds, replaced by the new one in the response."
    ),
    responses={
        400: {"description": "The refresh token is malformed."},
        401: {"description": "The refresh token was revoked or has expired."},
        404: {"description": "The user in the token no longer exists."},
    },
)
async def refresh_access_token(
    token_data: TokenRefreshRequestSchema,
    db: AsyncSession = Depends(get_db),
    jwt_manager: JWTAuthManager = Depends(get_jwt_auth_manager),
    settings: BaseAppSettings = Depends(get_settings),
) -> TokenRefreshResponseSchema:
    try:
        payload = jwt_manager.decode_refresh_token(token_data.refresh_token)
    except BaseSecurityError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    result = await db.execute(
        select(RefreshTokenModel).where(RefreshTokenModel.token == token_data.refresh_token)
    )
    token_record = result.scalars().first()
    if token_record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token not found."
        )

    if _is_expired(token_record.expires_at):
        await db.delete(token_record)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has expired."
        )

    user = await db.get(UserModel, payload.get("user_id"))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    new_refresh_token = jwt_manager.create_refresh_token({"user_id": user.id})
    await db.delete(token_record)
    await db.flush()
    db.add(
        RefreshTokenModel.create(
            user_id=cast(int, user.id),
            days_valid=settings.LOGIN_TIME_DAYS,
            token=new_refresh_token,
        )
    )
    await db.commit()

    return TokenRefreshResponseSchema(
        access_token=jwt_manager.create_access_token({"user_id": user.id}),
        refresh_token=new_refresh_token,
    )


@router.post(
    "/password-reset/request/",
    response_model=MessageResponseSchema,
    summary="Request a password reset link",
    description=(
        "Always answers with the same message, whether or not the address is "
        "registered, so the endpoint cannot be used to enumerate accounts."
    ),
)
async def request_password_reset(
    data: PasswordResetRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSender = Depends(get_accounts_email_notificator),
    settings: BaseAppSettings = Depends(get_settings),
) -> MessageResponseSchema:
    generic = MessageResponseSchema(message=GENERIC_RESET_MESSAGE)

    result = await db.execute(select(UserModel).where(UserModel.email == data.email))
    user = result.scalars().first()

    if user is None or not user.is_active:
        return generic

    await db.execute(
        delete(PasswordResetTokenModel).where(PasswordResetTokenModel.user_id == user.id)
    )
    reset_token = PasswordResetTokenModel.create(
        user_id=cast(int, user.id), hours_valid=settings.PASSWORD_RESET_TOKEN_TTL_HOURS
    )
    db.add(reset_token)
    await db.commit()

    reset_link = (
        f"{settings.BASE_FRONTEND_URL}/accounts/password-reset/complete/"
        f"?email={user.email}&token={reset_token.token}"
    )
    background_tasks.add_task(email_sender.send_password_reset_email, user.email, reset_link)

    return generic


@router.post(
    "/password-reset/complete/",
    response_model=MessageResponseSchema,
    summary="Set a new password using a reset token",
    description=(
        "An invalid or expired token is deleted on the spot, so a leaked link " "cannot be retried."
    ),
    responses={400: {"description": "The email or token is wrong, or the token expired."}},
)
async def reset_password(
    data: PasswordResetCompleteRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSender = Depends(get_accounts_email_notificator),
    settings: BaseAppSettings = Depends(get_settings),
) -> MessageResponseSchema:
    invalid = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email or token."
    )

    result = await db.execute(select(UserModel).where(UserModel.email == data.email))
    user = result.scalars().first()
    if user is None or not user.is_active:
        raise invalid

    token_result = await db.execute(
        select(PasswordResetTokenModel).where(PasswordResetTokenModel.user_id == user.id)
    )
    token_record = token_result.scalars().first()
    if token_record is None:
        raise invalid

    if token_record.token != data.token or _is_expired(token_record.expires_at):
        await db.delete(token_record)
        await db.commit()
        raise invalid

    try:
        user.set_password(data.password)
        await db.delete(token_record)
        await db.commit()
    except SQLAlchemyError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while resetting the password.",
        ) from error

    login_link = f"{settings.BASE_FRONTEND_URL}/accounts/login/"
    background_tasks.add_task(
        email_sender.send_password_reset_complete_email, user.email, login_link
    )

    return MessageResponseSchema(message="Password reset successfully.")


@router.post(
    "/password/change/",
    response_model=MessageResponseSchema,
    summary="Change your password while signed in",
    description="Requires the current password. All refresh tokens are revoked afterwards.",
    responses={400: {"description": "The current password is wrong."}},
)
async def change_password(
    data: PasswordChangeRequestSchema,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> MessageResponseSchema:
    if not current_user.verify_password(data.old_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect."
        )

    current_user.set_password(data.new_password)

    await db.execute(delete(RefreshTokenModel).where(RefreshTokenModel.user_id == current_user.id))
    await db.commit()

    return MessageResponseSchema(message="Password changed successfully.")


@router.patch(
    "/users/{user_id}/group/",
    response_model=UserDetailSchema,
    summary="Move a user into another group",
    description="Admin only. Accepts `user`, `moderator` or `admin` in the `group` field.",
    responses={
        403: {"description": "Caller is not an admin."},
        404: {"description": "No such user."},
    },
)
async def change_user_group(
    user_id: int,
    data: UserGroupUpdateRequestSchema,
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(require_admin),
) -> UserDetailSchema:
    user = await db.get(UserModel, user_id, options=[joinedload(UserModel.group)])
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    group_result = await db.execute(select(UserGroupModel).where(UserGroupModel.name == data.group))
    group = group_result.scalars().first()
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Requested group does not exist."
        )

    user.group_id = group.id
    await db.commit()
    await db.refresh(user, attribute_names=["group"])

    return UserDetailSchema.model_validate(user)


@router.post(
    "/users/{user_id}/activate/",
    response_model=UserDetailSchema,
    summary="Activate an account manually",
    description=(
        "Admin only. Activates a user without the emailed token and removes any "
        "pending activation token."
    ),
    responses={
        403: {"description": "Caller is not an admin."},
        404: {"description": "No such user."},
    },
)
async def activate_user_manually(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(require_admin),
) -> UserDetailSchema:
    user = await db.get(UserModel, user_id, options=[joinedload(UserModel.group)])
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    user.is_active = True
    await db.execute(delete(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id))
    await db.commit()

    return UserDetailSchema.model_validate(user)
