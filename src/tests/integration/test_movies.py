from decimal import Decimal

import pytest
from sqlalchemy import select

from database import (
    CertificationModel,
    GenreModel,
    MovieModel,
    OrderItemModel,
    OrderModel,
    OrderStatusEnum,
    StarModel,
    UserGroupEnum,
    UserGroupModel,
    UserModel,
)

MOVIES_URL = "/api/v1/cinema/movies/"
GENRES_URL = "/api/v1/cinema/genres/"
LOGIN_URL = "/api/v1/accounts/login/"

PASSWORD = "StrongPassword123!"


async def _make_user(
    db_session, email: str, group: UserGroupEnum = UserGroupEnum.USER
) -> UserModel:
    group_row = await db_session.execute(select(UserGroupModel).where(UserGroupModel.name == group))
    user = UserModel.create(
        email=email, raw_password=PASSWORD, group_id=group_row.scalars().first().id
    )
    user.is_active = True
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _auth_headers(client, email: str) -> dict[str, str]:
    login = await client.post(LOGIN_URL, json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed_movie(
    db_session,
    name: str = "Blade Runner",
    year: int = 1982,
    time: int = 117,
    imdb: float = 8.1,
    votes: int = 800_000,
    price: str = "9.99",
    genres: tuple[str, ...] = ("Sci-Fi",),
    stars: tuple[str, ...] = ("Harrison Ford",),
    description: str = "A blade runner hunts replicants.",
) -> MovieModel:
    cert_row = await db_session.execute(
        select(CertificationModel).where(CertificationModel.name == "R")
    )
    certification = cert_row.scalars().first()
    if certification is None:
        certification = CertificationModel(name="R")
        db_session.add(certification)
        await db_session.flush()

    genre_objects = []
    for genre_name in genres:
        row = await db_session.execute(select(GenreModel).where(GenreModel.name == genre_name))
        genre = row.scalars().first() or GenreModel(name=genre_name)
        db_session.add(genre)
        genre_objects.append(genre)

    star_objects = []
    for star_name in stars:
        row = await db_session.execute(select(StarModel).where(StarModel.name == star_name))
        star = row.scalars().first() or StarModel(name=star_name)
        db_session.add(star)
        star_objects.append(star)

    await db_session.flush()

    movie = MovieModel(
        name=name,
        year=year,
        time=time,
        imdb=imdb,
        votes=votes,
        description=description,
        price=Decimal(price),
        certification=certification,
        genres=genre_objects,
        stars=star_objects,
    )
    db_session.add(movie)
    await db_session.commit()
    await db_session.refresh(movie)
    return movie


@pytest.mark.asyncio
async def test_empty_catalog_returns_404(client):
    response = await client.get(MOVIES_URL)

    assert response.status_code == 404
    assert response.json()["detail"] == "No movies found."


@pytest.mark.asyncio
async def test_catalog_paginates(client, db_session):
    for index in range(12):
        await _seed_movie(db_session, name=f"Movie {index}", time=90 + index)

    first = await client.get(f"{MOVIES_URL}?page=1&per_page=5")
    assert first.status_code == 200
    body = first.json()

    assert len(body["movies"]) == 5
    assert body["total_items"] == 12
    assert body["total_pages"] == 3
    assert body["prev_page"] is None
    assert body["next_page"] == "/movies/?page=2&per_page=5"

    last = await client.get(f"{MOVIES_URL}?page=3&per_page=5")
    assert last.json()["next_page"] is None
    assert len(last.json()["movies"]) == 2


@pytest.mark.asyncio
async def test_catalog_page_beyond_the_end_returns_404(client, db_session):
    await _seed_movie(db_session)

    response = await client.get(f"{MOVIES_URL}?page=99")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_catalog_rejects_invalid_pagination(client):
    assert (await client.get(f"{MOVIES_URL}?page=0")).status_code == 422
    assert (await client.get(f"{MOVIES_URL}?per_page=0")).status_code == 422
    assert (await client.get(f"{MOVIES_URL}?per_page=50")).status_code == 422


@pytest.mark.asyncio
async def test_catalog_filters_by_year_range(client, db_session):
    await _seed_movie(db_session, name="Old", year=1975, time=100)
    await _seed_movie(db_session, name="Middle", year=1995, time=101)
    await _seed_movie(db_session, name="New", year=2015, time=102)

    response = await client.get(f"{MOVIES_URL}?year_from=1990&year_to=2000")

    body = response.json()
    assert body["total_items"] == 1
    assert body["movies"][0]["name"] == "Middle"


@pytest.mark.asyncio
async def test_catalog_filters_by_imdb_rating(client, db_session):
    await _seed_movie(db_session, name="Weak", imdb=4.0, time=100)
    await _seed_movie(db_session, name="Strong", imdb=9.0, time=101)

    response = await client.get(f"{MOVIES_URL}?imdb_min=8")

    body = response.json()
    assert body["total_items"] == 1
    assert body["movies"][0]["name"] == "Strong"


@pytest.mark.asyncio
async def test_catalog_filters_by_genre(client, db_session):
    await _seed_movie(db_session, name="Spacey", genres=("Sci-Fi",), time=100)
    await _seed_movie(db_session, name="Funny", genres=("Comedy",), time=101)

    response = await client.get(f"{MOVIES_URL}?genre=Comedy")

    body = response.json()
    assert body["total_items"] == 1
    assert body["movies"][0]["name"] == "Funny"


@pytest.mark.asyncio
async def test_catalog_sorts_by_price(client, db_session):
    await _seed_movie(db_session, name="Cheap", price="1.50", time=100)
    await _seed_movie(db_session, name="Pricey", price="20.00", time=101)

    ascending = await client.get(f"{MOVIES_URL}?sort_by=price&order=asc")
    names = [movie["name"] for movie in ascending.json()["movies"]]
    assert names == ["Cheap", "Pricey"]

    descending = await client.get(f"{MOVIES_URL}?sort_by=price&order=desc")
    names = [movie["name"] for movie in descending.json()["movies"]]
    assert names == ["Pricey", "Cheap"]


@pytest.mark.asyncio
async def test_catalog_search_matches_title_and_star(client, db_session):

    await _seed_movie(
        db_session,
        name="Blade Runner",
        stars=("Harrison Ford",),
        time=100,
        description="A detective hunts replicants.",
    )
    await _seed_movie(
        db_session,
        name="Amelie",
        stars=("Audrey Tautou",),
        time=101,
        description="A shy waitress decides to change the lives around her.",
    )

    by_title = await client.get(f"{MOVIES_URL}?search=blade")
    assert by_title.json()["total_items"] == 1

    by_star = await client.get(f"{MOVIES_URL}?search=tautou")
    assert by_star.json()["total_items"] == 1
    assert by_star.json()["movies"][0]["name"] == "Amelie"


@pytest.mark.asyncio
async def test_movie_detail_expands_related_entities(client, db_session):
    movie = await _seed_movie(db_session)

    response = await client.get(f"{MOVIES_URL}{movie.id}/")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Blade Runner"
    assert body["certification"]["name"] == "R"
    assert [genre["name"] for genre in body["genres"]] == ["Sci-Fi"]
    assert [star["name"] for star in body["stars"]] == ["Harrison Ford"]


@pytest.mark.asyncio
async def test_movie_detail_404_for_unknown_id(client):
    response = await client.get(f"{MOVIES_URL}999/")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_genres_endpoint_counts_movies(client, db_session):
    await _seed_movie(db_session, name="One", genres=("Drama",), time=100)
    await _seed_movie(db_session, name="Two", genres=("Drama",), time=101)
    await _seed_movie(db_session, name="Three", genres=("Comedy",), time=102)

    response = await client.get(GENRES_URL)

    assert response.status_code == 200
    counts = {row["name"]: row["movie_count"] for row in response.json()}
    assert counts == {"Comedy": 1, "Drama": 2}


def _movie_payload(**overrides) -> dict:
    payload = {
        "name": "Arrival",
        "year": 2016,
        "time": 116,
        "imdb": 7.9,
        "votes": 700000,
        "description": "A linguist is recruited to communicate with aliens.",
        "price": "12.50",
        "certification": "PG-13",
        "genres": ["Sci-Fi", "Drama"],
        "directors": ["Denis Villeneuve"],
        "stars": ["Amy Adams"],
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_moderator_can_create_a_movie(client, db_session, seed_user_groups):
    await _make_user(db_session, "mod@example.com", group=UserGroupEnum.MODERATOR)
    headers = await _auth_headers(client, "mod@example.com")

    response = await client.post(MOVIES_URL, json=_movie_payload(), headers=headers)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Arrival"
    assert body["certification"]["name"] == "PG-13"
    assert {genre["name"] for genre in body["genres"]} == {"Sci-Fi", "Drama"}
    assert [star["name"] for star in body["stars"]] == ["Amy Adams"]


@pytest.mark.asyncio
async def test_creating_a_movie_requires_moderator_rights(client, db_session, seed_user_groups):
    await _make_user(db_session, "plain@example.com")
    headers = await _auth_headers(client, "plain@example.com")

    response = await client.post(MOVIES_URL, json=_movie_payload(), headers=headers)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_creating_a_movie_requires_authentication(client, seed_user_groups):
    response = await client.post(MOVIES_URL, json=_movie_payload())

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_duplicate_movie_is_rejected(client, db_session, seed_user_groups):
    await _make_user(db_session, "mod@example.com", group=UserGroupEnum.MODERATOR)
    headers = await _auth_headers(client, "mod@example.com")

    first = await client.post(MOVIES_URL, json=_movie_payload(), headers=headers)
    assert first.status_code == 201

    second = await client.post(MOVIES_URL, json=_movie_payload(), headers=headers)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_moderator_can_update_a_movie(client, db_session, seed_user_groups):
    await _make_user(db_session, "mod@example.com", group=UserGroupEnum.MODERATOR)
    movie = await _seed_movie(db_session)
    headers = await _auth_headers(client, "mod@example.com")

    response = await client.patch(
        f"{MOVIES_URL}{movie.id}/",
        json={"price": "4.99", "genres": ["Cyberpunk"]},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["price"] == "4.99"
    assert [genre["name"] for genre in body["genres"]] == ["Cyberpunk"]
    assert body["name"] == "Blade Runner", "untouched fields must stay as they were"


@pytest.mark.asyncio
async def test_moderator_can_delete_an_unsold_movie(client, db_session, seed_user_groups):
    await _make_user(db_session, "mod@example.com", group=UserGroupEnum.MODERATOR)
    movie = await _seed_movie(db_session)
    headers = await _auth_headers(client, "mod@example.com")

    response = await client.delete(f"{MOVIES_URL}{movie.id}/", headers=headers)

    assert response.status_code == 204
    remaining = await db_session.execute(select(MovieModel).where(MovieModel.id == movie.id))
    assert remaining.scalars().first() is None


@pytest.mark.asyncio
async def test_purchased_movie_cannot_be_deleted(client, db_session, seed_user_groups):
    moderator = await _make_user(db_session, "mod@example.com", group=UserGroupEnum.MODERATOR)
    movie = await _seed_movie(db_session)

    paid_order = OrderModel(user_id=moderator.id, status=OrderStatusEnum.PAID)
    db_session.add(paid_order)
    await db_session.flush()
    db_session.add(
        OrderItemModel(order_id=paid_order.id, movie_id=movie.id, price_at_order=movie.price)
    )
    await db_session.commit()

    headers = await _auth_headers(client, "mod@example.com")
    response = await client.delete(f"{MOVIES_URL}{movie.id}/", headers=headers)

    assert response.status_code == 400
    assert "already been purchased" in response.json()["detail"]


@pytest.mark.asyncio
async def test_deleting_an_unknown_movie_returns_404(client, db_session, seed_user_groups):
    await _make_user(db_session, "mod@example.com", group=UserGroupEnum.MODERATOR)
    headers = await _auth_headers(client, "mod@example.com")

    response = await client.delete(f"{MOVIES_URL}999/", headers=headers)

    assert response.status_code == 404
