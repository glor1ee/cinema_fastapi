from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from database import (
    ActivationTokenModel,
    PasswordResetTokenModel,
    RefreshTokenModel,
    UserGroupEnum,
    UserGroupModel,
    UserModel,
)

REGISTER_URL = "/api/v1/accounts/register/"
ACTIVATE_URL = "/api/v1/accounts/activate/"
RESEND_URL = "/api/v1/accounts/activate/resend/"
LOGIN_URL = "/api/v1/accounts/login/"
LOGOUT_URL = "/api/v1/accounts/logout/"
REFRESH_URL = "/api/v1/accounts/refresh/"
RESET_REQUEST_URL = "/api/v1/accounts/password-reset/request/"
RESET_COMPLETE_URL = "/api/v1/accounts/password-reset/complete/"
CHANGE_PASSWORD_URL = "/api/v1/accounts/password/change/"

PASSWORD = "StrongPassword123!"


async def _register(client, email: str = "user@example.com", password: str = PASSWORD):
    return await client.post(REGISTER_URL, json={"email": email, "password": password})


async def _activate_via_email(client, db_session, email: str) -> None:
    result = await db_session.execute(
        select(ActivationTokenModel).join(UserModel).where(UserModel.email == email)
    )
    token = result.scalars().first()
    response = await client.post(ACTIVATE_URL, json={"email": email, "token": token.token})
    assert response.status_code == 200


async def _make_user(
    db_session, email: str, group: UserGroupEnum = UserGroupEnum.USER, active: bool = True
) -> UserModel:
    group_row = await db_session.execute(select(UserGroupModel).where(UserGroupModel.name == group))
    user = UserModel.create(
        email=email, raw_password=PASSWORD, group_id=group_row.scalars().first().id
    )
    user.is_active = active
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_register_creates_inactive_user_and_sends_activation_email(
    client, db_session, seed_user_groups, email_sender_stub
):
    response = await _register(client)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "user@example.com"
    assert "id" in body

    result = await db_session.execute(
        select(UserModel).where(UserModel.email == "user@example.com")
    )
    user = result.scalars().first()
    assert user is not None
    assert user.is_active is False, "a fresh account must not be active"

    token_result = await db_session.execute(
        select(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id)
    )
    assert token_result.scalars().first() is not None
    assert len(email_sender_stub.activation_emails) == 1


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email(client, seed_user_groups):
    assert (await _register(client)).status_code == 201
    second = await _register(client)

    assert second.status_code == 409
    assert "already exists" in second.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "password, expected",
    [
        ("short1!", "at least 8 characters"),
        ("nouppercase1!", "uppercase letter"),
        ("NOLOWERCASE1!", "lowercase letter"),
        ("NoDigitHere!", "at least one digit"),
        ("NoSpecial1234", "special character"),
    ],
)
async def test_register_enforces_password_complexity(client, seed_user_groups, password, expected):
    response = await _register(client, password=password)

    assert response.status_code == 422
    assert expected in str(response.json())


@pytest.mark.asyncio
async def test_activation_marks_user_active_and_consumes_token(
    client, db_session, seed_user_groups, email_sender_stub
):
    await _register(client)
    await _activate_via_email(client, db_session, "user@example.com")

    result = await db_session.execute(
        select(UserModel).where(UserModel.email == "user@example.com")
    )
    user = result.scalars().first()
    await db_session.refresh(user)
    assert user.is_active is True

    leftover = await db_session.execute(
        select(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id)
    )
    assert leftover.scalars().first() is None, "the token must be single-use"
    assert len(email_sender_stub.activation_complete_emails) == 1


@pytest.mark.asyncio
async def test_activation_rejects_expired_token(client, db_session, seed_user_groups):
    await _register(client)

    result = await db_session.execute(select(ActivationTokenModel))
    token = result.scalars().first()
    token.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db_session.commit()

    response = await client.post(
        ACTIVATE_URL, json={"email": "user@example.com", "token": token.token}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired activation token."


@pytest.mark.asyncio
async def test_activation_rejects_wrong_token(client, seed_user_groups):
    await _register(client)

    response = await client.post(
        ACTIVATE_URL, json={"email": "user@example.com", "token": "not-a-real-token"}
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_activation_rejects_already_active_account(client, db_session, seed_user_groups):
    await _register(client)
    result = await db_session.execute(select(ActivationTokenModel))
    token = result.scalars().first()

    user_result = await db_session.execute(select(UserModel))
    user = user_result.scalars().first()
    user.is_active = True
    await db_session.commit()

    response = await client.post(
        ACTIVATE_URL, json={"email": "user@example.com", "token": token.token}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "User account is already active."


@pytest.mark.asyncio
async def test_resend_activation_issues_a_new_token(
    client, db_session, seed_user_groups, email_sender_stub
):
    await _register(client)
    first = (await db_session.execute(select(ActivationTokenModel))).scalars().first()
    first_token = first.token

    response = await client.post(RESEND_URL, json={"email": "user@example.com"})
    assert response.status_code == 200

    db_session.expire_all()
    second = (await db_session.execute(select(ActivationTokenModel))).scalars().first()
    assert second.token != first_token, "resending must replace the old token"
    assert len(email_sender_stub.activation_emails) == 2


@pytest.mark.asyncio
async def test_resend_activation_hides_whether_the_email_exists(
    client, seed_user_groups, email_sender_stub
):
    response = await client.post(RESEND_URL, json={"email": "nobody@example.com"})

    assert response.status_code == 200
    assert email_sender_stub.activation_emails == [], "no email for an unknown address"


@pytest.mark.asyncio
async def test_login_returns_token_pair_and_stores_refresh_token(
    client, db_session, seed_user_groups
):
    user = await _make_user(db_session, "active@example.com")

    response = await client.post(
        LOGIN_URL, json={"email": "active@example.com", "password": PASSWORD}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"

    stored = await db_session.execute(
        select(RefreshTokenModel).where(RefreshTokenModel.user_id == user.id)
    )
    assert stored.scalars().first().token == body["refresh_token"]


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(client, db_session, seed_user_groups):
    await _make_user(db_session, "active@example.com")

    response = await client.post(
        LOGIN_URL, json={"email": "active@example.com", "password": "WrongPassword1!"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


@pytest.mark.asyncio
async def test_login_rejects_unknown_email(client, seed_user_groups):
    response = await client.post(
        LOGIN_URL, json={"email": "ghost@example.com", "password": PASSWORD}
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_rejects_inactive_account(client, db_session, seed_user_groups):
    await _make_user(db_session, "inactive@example.com", active=False)

    response = await client.post(
        LOGIN_URL, json={"email": "inactive@example.com", "password": PASSWORD}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "User account is not activated."


@pytest.mark.asyncio
async def test_logout_revokes_the_refresh_token(client, db_session, seed_user_groups):
    await _make_user(db_session, "active@example.com")
    login = await client.post(LOGIN_URL, json={"email": "active@example.com", "password": PASSWORD})
    tokens = login.json()

    response = await client.post(
        LOGOUT_URL,
        json={"refresh_token": tokens["refresh_token"]},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert response.status_code == 200

    refresh = await client.post(REFRESH_URL, json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 401
    assert refresh.json()["detail"] == "Refresh token not found."


@pytest.mark.asyncio
async def test_logout_requires_authentication(client):
    response = await client.post(LOGOUT_URL, json={"refresh_token": "whatever"})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_returns_a_new_access_token(
    client, db_session, seed_user_groups, jwt_manager
):
    user = await _make_user(db_session, "active@example.com")
    login = await client.post(LOGIN_URL, json={"email": "active@example.com", "password": PASSWORD})

    response = await client.post(REFRESH_URL, json={"refresh_token": login.json()["refresh_token"]})

    assert response.status_code == 200
    payload = jwt_manager.decode_access_token(response.json()["access_token"])
    assert payload["user_id"] == user.id


@pytest.mark.asyncio
async def test_refresh_rejects_a_malformed_token(client):
    response = await client.post(REFRESH_URL, json={"refresh_token": "not.a.jwt"})

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_refresh_rotates_the_refresh_token(client, db_session, seed_user_groups):
    await _make_user(db_session, "active@example.com")
    login = await client.post(LOGIN_URL, json={"email": "active@example.com", "password": PASSWORD})
    old_refresh_token = login.json()["refresh_token"]

    first = await client.post(REFRESH_URL, json={"refresh_token": old_refresh_token})
    assert first.status_code == 200
    new_refresh_token = first.json()["refresh_token"]
    assert new_refresh_token != old_refresh_token

    reuse = await client.post(REFRESH_URL, json={"refresh_token": old_refresh_token})
    assert reuse.status_code == 401

    second = await client.post(REFRESH_URL, json={"refresh_token": new_refresh_token})
    assert second.status_code == 200


@pytest.mark.asyncio
async def test_refresh_rejects_a_token_expired_in_the_database(
    client, db_session, seed_user_groups
):
    user = await _make_user(db_session, "active@example.com")
    login = await client.post(LOGIN_URL, json={"email": "active@example.com", "password": PASSWORD})
    refresh_token = login.json()["refresh_token"]

    result = await db_session.execute(
        select(RefreshTokenModel).where(RefreshTokenModel.user_id == user.id)
    )
    token_record = result.scalars().first()
    token_record.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db_session.commit()

    response = await client.post(REFRESH_URL, json={"refresh_token": refresh_token})

    assert response.status_code == 401
    assert response.json()["detail"] == "Refresh token has expired."


@pytest.mark.asyncio
async def test_password_reset_request_is_silent_about_unknown_emails(
    client, seed_user_groups, email_sender_stub
):
    response = await client.post(RESET_REQUEST_URL, json={"email": "ghost@example.com"})

    assert response.status_code == 200
    assert email_sender_stub.password_reset_emails == []


@pytest.mark.asyncio
async def test_password_reset_flow_sets_a_new_password(
    client, db_session, seed_user_groups, email_sender_stub
):
    user = await _make_user(db_session, "active@example.com")

    request = await client.post(RESET_REQUEST_URL, json={"email": "active@example.com"})
    assert request.status_code == 200
    assert len(email_sender_stub.password_reset_emails) == 1

    token_row = await db_session.execute(
        select(PasswordResetTokenModel).where(PasswordResetTokenModel.user_id == user.id)
    )
    token = token_row.scalars().first()

    new_password = "BrandNewPassword1!"
    complete = await client.post(
        RESET_COMPLETE_URL,
        json={
            "email": "active@example.com",
            "token": token.token,
            "password": new_password,
        },
    )
    assert complete.status_code == 200

    await db_session.refresh(user)
    assert user.verify_password(new_password)

    login = await client.post(
        LOGIN_URL, json={"email": "active@example.com", "password": new_password}
    )
    assert login.status_code == 201


@pytest.mark.asyncio
async def test_password_reset_deletes_the_token_when_it_is_wrong(
    client, db_session, seed_user_groups
):
    user = await _make_user(db_session, "active@example.com")
    await client.post(RESET_REQUEST_URL, json={"email": "active@example.com"})

    response = await client.post(
        RESET_COMPLETE_URL,
        json={
            "email": "active@example.com",
            "token": "wrong-token",
            "password": "BrandNewPassword1!",
        },
    )

    assert response.status_code == 400
    await db_session.commit()
    leftover = await db_session.execute(
        select(PasswordResetTokenModel).where(PasswordResetTokenModel.user_id == user.id)
    )
    assert leftover.scalars().first() is None, "a bad attempt must burn the token"


@pytest.mark.asyncio
async def test_change_password_requires_the_current_one(client, db_session, seed_user_groups):
    await _make_user(db_session, "active@example.com")
    login = await client.post(LOGIN_URL, json={"email": "active@example.com", "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    wrong = await client.post(
        CHANGE_PASSWORD_URL,
        json={"old_password": "NotThePassword1!", "new_password": "BrandNewPassword1!"},
        headers=headers,
    )
    assert wrong.status_code == 400

    correct = await client.post(
        CHANGE_PASSWORD_URL,
        json={"old_password": PASSWORD, "new_password": "BrandNewPassword1!"},
        headers=headers,
    )
    assert correct.status_code == 200

    login_again = await client.post(
        LOGIN_URL, json={"email": "active@example.com", "password": "BrandNewPassword1!"}
    )
    assert login_again.status_code == 201


async def _auth_headers(client, email: str) -> dict[str, str]:
    login = await client.post(LOGIN_URL, json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_admin_can_change_a_user_group(client, db_session, seed_user_groups):
    await _make_user(db_session, "admin@example.com", group=UserGroupEnum.ADMIN)
    target = await _make_user(db_session, "plain@example.com")
    headers = await _auth_headers(client, "admin@example.com")

    response = await client.patch(
        f"/api/v1/accounts/users/{target.id}/group/",
        json={"group": "moderator"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["group"] == "moderator"


@pytest.mark.asyncio
async def test_regular_user_cannot_change_groups(client, db_session, seed_user_groups):
    await _make_user(db_session, "plain@example.com")
    target = await _make_user(db_session, "other@example.com")
    headers = await _auth_headers(client, "plain@example.com")

    response = await client.patch(
        f"/api/v1/accounts/users/{target.id}/group/",
        json={"group": "admin"},
        headers=headers,
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_activate_an_account_manually(client, db_session, seed_user_groups):
    await _make_user(db_session, "admin@example.com", group=UserGroupEnum.ADMIN)
    target = await _make_user(db_session, "pending@example.com", active=False)
    headers = await _auth_headers(client, "admin@example.com")

    response = await client.post(f"/api/v1/accounts/users/{target.id}/activate/", headers=headers)

    assert response.status_code == 200
    assert response.json()["is_active"] is True

    await db_session.refresh(target)
    assert target.is_active is True


@pytest.mark.asyncio
async def test_moderator_cannot_activate_accounts(client, db_session, seed_user_groups):
    await _make_user(db_session, "mod@example.com", group=UserGroupEnum.MODERATOR)
    target = await _make_user(db_session, "pending@example.com", active=False)
    headers = await _auth_headers(client, "mod@example.com")

    response = await client.post(f"/api/v1/accounts/users/{target.id}/activate/", headers=headers)

    assert response.status_code == 403
