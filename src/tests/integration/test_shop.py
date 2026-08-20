from decimal import Decimal

import pytest
from sqlalchemy import select

from database import (
    CertificationModel,
    GenreModel,
    MovieModel,
    OrderModel,
    OrderStatusEnum,
    UserGroupEnum,
    UserGroupModel,
    UserModel,
)

LOGIN_URL = "/api/v1/accounts/login/"
CART_URL = "/api/v1/shop/cart/"
CART_ITEMS_URL = "/api/v1/shop/cart/items/"
ORDERS_URL = "/api/v1/shop/orders/"
ADMIN_ORDERS_URL = "/api/v1/shop/admin/orders/"

PASSWORD = "StrongPassword123!"


async def _make_user(
    db_session, email: str, group: UserGroupEnum = UserGroupEnum.USER
) -> UserModel:
    row = await db_session.execute(select(UserGroupModel).where(UserGroupModel.name == group))
    user = UserModel.create(email=email, raw_password=PASSWORD, group_id=row.scalars().first().id)
    user.is_active = True
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _auth_headers(client, email: str) -> dict[str, str]:
    login = await client.post(LOGIN_URL, json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed_movie(
    db_session, name: str, price: str = "10.00", time_minutes: int = 100
) -> MovieModel:
    cert_row = await db_session.execute(
        select(CertificationModel).where(CertificationModel.name == "PG")
    )
    certification = cert_row.scalars().first()
    if certification is None:
        certification = CertificationModel(name="PG")
        db_session.add(certification)
        await db_session.flush()

    genre_row = await db_session.execute(select(GenreModel).where(GenreModel.name == "Drama"))
    genre = genre_row.scalars().first()
    if genre is None:
        genre = GenreModel(name="Drama")
        db_session.add(genre)
        await db_session.flush()

    movie = MovieModel(
        name=name,
        year=2000,
        time=time_minutes,
        imdb=7.0,
        votes=1000,
        description=f"Description of {name}.",
        price=Decimal(price),
        certification=certification,
        genres=[genre],
    )
    db_session.add(movie)
    await db_session.commit()
    await db_session.refresh(movie)
    return movie


@pytest.mark.asyncio
async def test_cart_requires_authentication(client):
    assert (await client.get(CART_URL)).status_code == 401


@pytest.mark.asyncio
async def test_new_cart_starts_empty(client, db_session, seed_user_groups):
    await _make_user(db_session, "buyer@example.com")
    headers = await _auth_headers(client, "buyer@example.com")

    response = await client.get(CART_URL, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert Decimal(body["total_amount"]) == Decimal("0.00")


@pytest.mark.asyncio
async def test_add_to_cart_returns_details_and_total(client, db_session, seed_user_groups):
    await _make_user(db_session, "buyer@example.com")
    movie = await _seed_movie(db_session, "Heat", price="12.50")
    headers = await _auth_headers(client, "buyer@example.com")

    response = await client.post(CART_ITEMS_URL, json={"movie_id": movie.id}, headers=headers)

    assert response.status_code == 201
    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["name"] == "Heat"
    assert item["year"] == 2000
    assert item["genres"] == ["Drama"]
    assert Decimal(body["total_amount"]) == Decimal("12.50")


@pytest.mark.asyncio
async def test_cannot_add_the_same_movie_twice(client, db_session, seed_user_groups):
    await _make_user(db_session, "buyer@example.com")
    movie = await _seed_movie(db_session, "Heat")
    headers = await _auth_headers(client, "buyer@example.com")

    first = await client.post(CART_ITEMS_URL, json={"movie_id": movie.id}, headers=headers)
    assert first.status_code == 201

    second = await client.post(CART_ITEMS_URL, json={"movie_id": movie.id}, headers=headers)
    assert second.status_code == 400
    assert "already in your cart" in second.json()["detail"]


@pytest.mark.asyncio
async def test_cannot_add_an_unknown_movie(client, db_session, seed_user_groups):
    await _make_user(db_session, "buyer@example.com")
    headers = await _auth_headers(client, "buyer@example.com")

    response = await client.post(CART_ITEMS_URL, json={"movie_id": 999}, headers=headers)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cannot_add_an_already_purchased_movie(client, db_session, seed_user_groups):
    user = await _make_user(db_session, "buyer@example.com")
    movie = await _seed_movie(db_session, "Heat")
    headers = await _auth_headers(client, "buyer@example.com")

    await client.post(CART_ITEMS_URL, json={"movie_id": movie.id}, headers=headers)
    order_response = await client.post(ORDERS_URL, headers=headers)
    order_id = order_response.json()["order"]["id"]

    order = await db_session.get(OrderModel, order_id)
    order.status = OrderStatusEnum.PAID
    await db_session.commit()

    response = await client.post(CART_ITEMS_URL, json={"movie_id": movie.id}, headers=headers)

    assert response.status_code == 400
    assert "already purchased" in response.json()["detail"]
    assert user is not None


@pytest.mark.asyncio
async def test_remove_from_cart(client, db_session, seed_user_groups):
    await _make_user(db_session, "buyer@example.com")
    movie = await _seed_movie(db_session, "Heat")
    headers = await _auth_headers(client, "buyer@example.com")
    await client.post(CART_ITEMS_URL, json={"movie_id": movie.id}, headers=headers)

    response = await client.delete(f"{CART_ITEMS_URL}{movie.id}/", headers=headers)

    assert response.status_code == 200
    assert response.json()["items"] == []


@pytest.mark.asyncio
async def test_removing_a_movie_that_is_not_in_the_cart_returns_404(
    client, db_session, seed_user_groups
):
    await _make_user(db_session, "buyer@example.com")
    movie = await _seed_movie(db_session, "Heat")
    headers = await _auth_headers(client, "buyer@example.com")

    response = await client.delete(f"{CART_ITEMS_URL}{movie.id}/", headers=headers)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_clear_cart_empties_everything(client, db_session, seed_user_groups):
    await _make_user(db_session, "buyer@example.com")
    first = await _seed_movie(db_session, "Heat", time_minutes=100)
    second = await _seed_movie(db_session, "Collateral", time_minutes=101)
    headers = await _auth_headers(client, "buyer@example.com")
    await client.post(CART_ITEMS_URL, json={"movie_id": first.id}, headers=headers)
    await client.post(CART_ITEMS_URL, json={"movie_id": second.id}, headers=headers)

    response = await client.delete(CART_URL, headers=headers)

    assert response.status_code == 200
    cart = await client.get(CART_URL, headers=headers)
    assert cart.json()["items"] == []


@pytest.mark.asyncio
async def test_moderator_can_inspect_another_cart(client, db_session, seed_user_groups):
    buyer = await _make_user(db_session, "buyer@example.com")
    await _make_user(db_session, "mod@example.com", group=UserGroupEnum.MODERATOR)
    movie = await _seed_movie(db_session, "Heat")

    buyer_headers = await _auth_headers(client, "buyer@example.com")
    await client.post(CART_ITEMS_URL, json={"movie_id": movie.id}, headers=buyer_headers)

    mod_headers = await _auth_headers(client, "mod@example.com")
    response = await client.get(f"/api/v1/shop/users/{buyer.id}/cart/", headers=mod_headers)

    assert response.status_code == 200
    assert response.json()["items"][0]["name"] == "Heat"


@pytest.mark.asyncio
async def test_regular_user_cannot_inspect_another_cart(client, db_session, seed_user_groups):
    buyer = await _make_user(db_session, "buyer@example.com")
    await _make_user(db_session, "nosy@example.com")
    headers = await _auth_headers(client, "nosy@example.com")

    response = await client.get(f"/api/v1/shop/users/{buyer.id}/cart/", headers=headers)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_cannot_order_an_empty_cart(client, db_session, seed_user_groups):
    await _make_user(db_session, "buyer@example.com")
    headers = await _auth_headers(client, "buyer@example.com")

    response = await client.post(ORDERS_URL, headers=headers)

    assert response.status_code == 400
    assert response.json()["detail"] == "Your cart is empty."


@pytest.mark.asyncio
async def test_placing_an_order_moves_the_cart_into_it(client, db_session, seed_user_groups):
    await _make_user(db_session, "buyer@example.com")
    first = await _seed_movie(db_session, "Heat", price="10.00", time_minutes=100)
    second = await _seed_movie(db_session, "Collateral", price="5.50", time_minutes=101)
    headers = await _auth_headers(client, "buyer@example.com")
    await client.post(CART_ITEMS_URL, json={"movie_id": first.id}, headers=headers)
    await client.post(CART_ITEMS_URL, json={"movie_id": second.id}, headers=headers)

    response = await client.post(ORDERS_URL, headers=headers)

    assert response.status_code == 201
    body = response.json()
    order = body["order"]
    assert order["status"] == "pending"
    assert len(order["items"]) == 2
    assert Decimal(order["total_amount"]) == Decimal("15.50")
    assert body["excluded"] == []

    cart = await client.get(CART_URL, headers=headers)
    assert cart.json()["items"] == [], "the cart is emptied once it becomes an order"


@pytest.mark.asyncio
async def test_order_freezes_the_price(client, db_session, seed_user_groups):
    await _make_user(db_session, "buyer@example.com")
    movie = await _seed_movie(db_session, "Heat", price="10.00")
    headers = await _auth_headers(client, "buyer@example.com")
    await client.post(CART_ITEMS_URL, json={"movie_id": movie.id}, headers=headers)
    order_response = await client.post(ORDERS_URL, headers=headers)
    order_id = order_response.json()["order"]["id"]

    movie.price = Decimal("99.99")
    await db_session.commit()

    detail = await client.get(f"{ORDERS_URL}{order_id}/", headers=headers)
    assert Decimal(detail.json()["items"][0]["price_at_order"]) == Decimal("10.00")


@pytest.mark.asyncio
async def test_order_excludes_movies_from_a_pending_order(client, db_session, seed_user_groups):
    await _make_user(db_session, "buyer@example.com")
    movie = await _seed_movie(db_session, "Heat")
    headers = await _auth_headers(client, "buyer@example.com")

    await client.post(CART_ITEMS_URL, json={"movie_id": movie.id}, headers=headers)
    await client.post(ORDERS_URL, headers=headers)

    await client.post(CART_ITEMS_URL, json={"movie_id": movie.id}, headers=headers)
    response = await client.post(ORDERS_URL, headers=headers)

    assert response.status_code == 400
    assert "None of the movies" in response.json()["detail"]


@pytest.mark.asyncio
async def test_order_list_and_detail(client, db_session, seed_user_groups):
    await _make_user(db_session, "buyer@example.com")
    movie = await _seed_movie(db_session, "Heat")
    headers = await _auth_headers(client, "buyer@example.com")
    await client.post(CART_ITEMS_URL, json={"movie_id": movie.id}, headers=headers)
    created = await client.post(ORDERS_URL, headers=headers)
    order_id = created.json()["order"]["id"]

    listing = await client.get(ORDERS_URL, headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    detail = await client.get(f"{ORDERS_URL}{order_id}/", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["items"][0]["name"] == "Heat"


@pytest.mark.asyncio
async def test_cannot_read_someone_elses_order(client, db_session, seed_user_groups):
    await _make_user(db_session, "buyer@example.com")
    await _make_user(db_session, "other@example.com")
    movie = await _seed_movie(db_session, "Heat")

    buyer_headers = await _auth_headers(client, "buyer@example.com")
    await client.post(CART_ITEMS_URL, json={"movie_id": movie.id}, headers=buyer_headers)
    created = await client.post(ORDERS_URL, headers=buyer_headers)
    order_id = created.json()["order"]["id"]

    other_headers = await _auth_headers(client, "other@example.com")
    response = await client.get(f"{ORDERS_URL}{order_id}/", headers=other_headers)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cancel_a_pending_order(client, db_session, seed_user_groups):
    await _make_user(db_session, "buyer@example.com")
    movie = await _seed_movie(db_session, "Heat")
    headers = await _auth_headers(client, "buyer@example.com")
    await client.post(CART_ITEMS_URL, json={"movie_id": movie.id}, headers=headers)
    created = await client.post(ORDERS_URL, headers=headers)
    order_id = created.json()["order"]["id"]

    response = await client.post(f"{ORDERS_URL}{order_id}/cancel/", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "canceled"

    again = await client.post(f"{ORDERS_URL}{order_id}/cancel/", headers=headers)
    assert again.status_code == 400


@pytest.mark.asyncio
async def test_paid_order_cannot_be_cancelled(client, db_session, seed_user_groups):
    await _make_user(db_session, "buyer@example.com")
    movie = await _seed_movie(db_session, "Heat")
    headers = await _auth_headers(client, "buyer@example.com")
    await client.post(CART_ITEMS_URL, json={"movie_id": movie.id}, headers=headers)
    created = await client.post(ORDERS_URL, headers=headers)
    order_id = created.json()["order"]["id"]

    order = await db_session.get(OrderModel, order_id)
    order.status = OrderStatusEnum.PAID
    await db_session.commit()

    response = await client.post(f"{ORDERS_URL}{order_id}/cancel/", headers=headers)

    assert response.status_code == 400
    assert "refund" in response.json()["detail"]


@pytest.mark.asyncio
async def test_moderator_can_filter_all_orders(client, db_session, seed_user_groups):
    buyer = await _make_user(db_session, "buyer@example.com")
    await _make_user(db_session, "mod@example.com", group=UserGroupEnum.MODERATOR)
    movie = await _seed_movie(db_session, "Heat")

    buyer_headers = await _auth_headers(client, "buyer@example.com")
    await client.post(CART_ITEMS_URL, json={"movie_id": movie.id}, headers=buyer_headers)
    await client.post(ORDERS_URL, headers=buyer_headers)

    mod_headers = await _auth_headers(client, "mod@example.com")

    everything = await client.get(ADMIN_ORDERS_URL, headers=mod_headers)
    assert everything.status_code == 200
    assert len(everything.json()) == 1

    by_user = await client.get(f"{ADMIN_ORDERS_URL}?user_id={buyer.id}", headers=mod_headers)
    assert len(by_user.json()) == 1

    by_status = await client.get(f"{ADMIN_ORDERS_URL}?order_status=paid", headers=mod_headers)
    assert by_status.json() == [], "the only order is still pending"


@pytest.mark.asyncio
async def test_regular_user_cannot_browse_all_orders(client, db_session, seed_user_groups):
    await _make_user(db_session, "buyer@example.com")
    headers = await _auth_headers(client, "buyer@example.com")

    response = await client.get(ADMIN_ORDERS_URL, headers=headers)

    assert response.status_code == 403
