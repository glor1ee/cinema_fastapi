from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from database import (
    ActivationTokenModel,
    PasswordResetTokenModel,
    UserGroupEnum,
    UserGroupModel,
    UserModel,
)
from tasks.tokens import delete_expired_tokens

PASSWORD = "StrongPassword123!"


async def _make_user(db_session, email: str) -> UserModel:
    row = await db_session.execute(
        select(UserGroupModel).where(UserGroupModel.name == UserGroupEnum.USER)
    )
    user = UserModel.create(email=email, raw_password=PASSWORD, group_id=row.scalars().first().id)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_cleanup_removes_only_expired_activation_tokens(db_session, seed_user_groups):
    stale_user = await _make_user(db_session, "stale@example.com")
    fresh_user = await _make_user(db_session, "fresh@example.com")

    db_session.add(
        ActivationTokenModel(
            user_id=stale_user.id,
            token="expired-activation-token",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    db_session.add(
        ActivationTokenModel(
            user_id=fresh_user.id,
            token="valid-activation-token",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )
    await db_session.commit()

    removed = await delete_expired_tokens(db_session)

    assert removed["activation_tokens"] == 1

    remaining = await db_session.execute(select(ActivationTokenModel))
    tokens = remaining.scalars().all()
    assert len(tokens) == 1
    assert tokens[0].token == "valid-activation-token"


@pytest.mark.asyncio
async def test_cleanup_removes_expired_password_reset_tokens(db_session, seed_user_groups):
    user = await _make_user(db_session, "user@example.com")
    db_session.add(
        PasswordResetTokenModel(
            user_id=user.id,
            token="expired-reset-token",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
    )
    await db_session.commit()

    removed = await delete_expired_tokens(db_session)

    assert removed["password_reset_tokens"] == 1
    remaining = await db_session.execute(select(PasswordResetTokenModel))
    assert remaining.scalars().first() is None


@pytest.mark.asyncio
async def test_cleanup_is_safe_to_run_on_an_empty_database(db_session):
    removed = await delete_expired_tokens(db_session)

    assert removed == {"activation_tokens": 0, "password_reset_tokens": 0}


@pytest.mark.asyncio
async def test_expired_token_no_longer_blocks_a_new_one(db_session, seed_user_groups):
    user = await _make_user(db_session, "user@example.com")
    db_session.add(
        ActivationTokenModel(
            user_id=user.id,
            token="expired-activation-token",
            expires_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
    )
    await db_session.commit()

    await delete_expired_tokens(db_session)

    db_session.add(ActivationTokenModel.create(user_id=user.id, hours_valid=24))
    await db_session.commit()

    tokens = await db_session.execute(select(ActivationTokenModel))
    assert len(tokens.scalars().all()) == 1
