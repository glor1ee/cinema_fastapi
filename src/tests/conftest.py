import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_accounts_email_notificator, get_settings
from database import UserGroupEnum, UserGroupModel, get_db_contextmanager, reset_database
from main import app
from security.token_manager import JWTAuthManager
from tests.doubles.emails import StubEmailSender


@pytest_asyncio.fixture(scope="function", autouse=True)
async def reset_db():
    await reset_database()
    yield


@pytest_asyncio.fixture(scope="function")
async def email_sender_stub() -> StubEmailSender:
    return StubEmailSender()


@pytest_asyncio.fixture(scope="function")
async def client(email_sender_stub: StubEmailSender):
    app.dependency_overrides[get_accounts_email_notificator] = lambda: email_sender_stub

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        yield async_client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncSession:
    async with get_db_contextmanager() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def seed_user_groups(db_session: AsyncSession) -> AsyncSession:
    await db_session.execute(
        insert(UserGroupModel).values([{"name": group.value} for group in UserGroupEnum])
    )
    await db_session.commit()
    return db_session


@pytest_asyncio.fixture(scope="function")
async def jwt_manager() -> JWTAuthManager:
    settings = get_settings()
    return JWTAuthManager(
        secret_key_access=settings.SECRET_KEY_ACCESS,
        secret_key_refresh=settings.SECRET_KEY_REFRESH,
        algorithm=settings.JWT_SIGNING_ALGORITHM,
    )
