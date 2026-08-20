import asyncio
from datetime import datetime, timezone
from typing import cast

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from database import ActivationTokenModel, PasswordResetTokenModel, get_db_contextmanager
from tasks.celery_app import celery_app


async def delete_expired_tokens(db: AsyncSession) -> dict[str, int]:
    now = datetime.now(timezone.utc)

    activation_result = cast(
        CursorResult,
        await db.execute(delete(ActivationTokenModel).where(ActivationTokenModel.expires_at < now)),
    )
    password_result = cast(
        CursorResult,
        await db.execute(
            delete(PasswordResetTokenModel).where(PasswordResetTokenModel.expires_at < now)
        ),
    )
    await db.commit()

    return {
        "activation_tokens": activation_result.rowcount or 0,
        "password_reset_tokens": password_result.rowcount or 0,
    }


async def _purge() -> dict[str, int]:
    async with get_db_contextmanager() as db:
        return await delete_expired_tokens(db)


@celery_app.task(name="tasks.tokens.purge_expired_tokens")
def purge_expired_tokens() -> dict[str, int]:
    return asyncio.run(_purge())
