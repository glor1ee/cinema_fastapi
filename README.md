# Online Cinema

A FastAPI backend for an online cinema. Users confirm their email, browse a
movie catalog, collect movies in a cart and turn that cart into an order.

## Implemented functionality

Eight functions were selected from the Online Cinema specification.

| # | Function | Where |
|---|----------|-------|
| 1 | Registration with email activation, resend, scheduled token cleanup | `routes/accounts.py`, `tasks/tokens.py` |
| 2 | Login and logout with server-side refresh-token revocation | `routes/accounts.py` |
| 3 | Password change and forgotten-password reset | `routes/accounts.py` |
| 4 | User groups: user, moderator, admin | `config/dependencies.py`, `routes/accounts.py` |
| 5 | Movie catalog: pagination, filtering, sorting, search | `routes/movies.py` |
| 6 | Moderator movie CRUD with a delete guard on sold movies | `routes/movies.py` |
| 7 | Shopping cart | `routes/cart.py` |
| 8 | Orders | `routes/orders.py` |

## Tech stack

FastAPI · Pydantic v2 · SQLAlchemy 2.0 (async) · PostgreSQL · Alembic ·
Celery + Redis · Poetry · pytest + pytest-cov · Docker Compose

## Running the project

### Docker Compose

```bash
cp .env.sample .env
docker compose up --build
```

This starts PostgreSQL, Redis, MailHog, the API, a Celery worker and Celery
beat. Migrations run automatically before the API comes up.

- API — `http://localhost:8000`
- Documentation — `http://localhost:8000/docs`
- Captured emails — `http://localhost:8025`

### Locally

```bash
poetry install
cp .env.sample .env
alembic upgrade head
uvicorn main:app --reload --app-dir src
```

## Documentation access

`/docs`, `/redoc` and `/openapi.json` sit behind HTTP Basic Auth so the full
API surface is not published to anonymous visitors. Credentials come from
`DOCS_USERNAME` and `DOCS_PASSWORD` in `.env`.

## Tests

```bash
pytest                  # runs the suite and enforces the coverage floor
flake8 src
black --check src
mypy src
```

`pytest.ini` fails the run below **60%** coverage. The suite currently reports
**90%** across 85 tests. An HTML report is written to `htmlcov/`.

One configuration detail matters here: `pyproject.toml` sets
`concurrency = ["greenlet", "thread"]` for coverage. SQLAlchemy's async layer
switches greenlets on every database `await`, and without that setting coverage
stops tracing each endpoint body at its first query and under-reports the suite
by roughly twenty points.

---

# API reference

Every route is prefixed with `/api/v1`. Endpoints that need a signed-in user
expect `Authorization: Bearer <access_token>`.

## Accounts — `/api/v1/accounts`

| Method | Path | Access |
|--------|------|--------|
| POST | `/register/` | public |
| POST | `/activate/` | public |
| POST | `/activate/resend/` | public |
| POST | `/login/` | public |
| POST | `/logout/` | signed in |
| POST | `/refresh/` | public |
| POST | `/password-reset/request/` | public |
| POST | `/password-reset/complete/` | public |
| POST | `/password/change/` | signed in |
| PATCH | `/users/{user_id}/group/` | admin |
| POST | `/users/{user_id}/activate/` | admin |

### `POST /register/`

Creates an account in the `user` group and emails an activation link valid for
24 hours. The account is inactive and cannot sign in until it is confirmed.

```json
{ "email": "user@example.com", "password": "StrongPassword123!" }
```

The password must be at least 8 characters and contain an uppercase letter, a
lowercase letter, a digit and one of `@ $ ! % * ? & #`. Returns `201` with the
new id and email, `409` when the email is taken, `422` when the password is
too weak.

### `POST /activate/resend/`

**What it does:** issues a replacement activation token when the first one
expired, deleting the old one first.

```json
{ "email": "user@example.com" }
```

Always returns `200` with the same message, whether or not the address is
registered and whether or not it still needs activating. That is deliberate:
a different answer per case would let anyone probe which emails have accounts.

### `POST /logout/`

**What it does:** deletes the supplied refresh token from the database, so it
stops working immediately even though its signature is still cryptographically
valid. This is why refresh tokens are stored server-side at all.

```json
{ "refresh_token": "<token from login>" }
```

Requires the access token in the header as well; a user can only revoke their
own refresh tokens. Returns `401` if the token is unknown or belongs to
someone else.

### `POST /password/change/`

**What it does:** changes the password of the signed-in user, then revokes
**all** of that user's refresh tokens, so sessions opened elsewhere stop
working.

```json
{ "old_password": "StrongPassword123!", "new_password": "BrandNewPassword1!" }
```

Returns `400` when the current password does not match.

### `POST /password-reset/complete/`

Sets a new password using the token from the reset email.

```json
{
  "email": "user@example.com",
  "token": "<token from the email>",
  "password": "BrandNewPassword1!"
}
```

**Worth knowing:** a wrong or expired token is deleted on the spot rather than
left in place, so a leaked link cannot be retried. All failure modes answer
with the same `400 Invalid email or token.`

### `PATCH /users/{user_id}/group/` · `POST /users/{user_id}/activate/`

Admin-only. The first moves a user into `user`, `moderator` or `admin`; the
second activates an account without the emailed token and clears any pending
activation token. Both return the updated user, `403` for non-admins and `404`
for an unknown id.

## Catalog — `/api/v1/cinema`

| Method | Path | Access |
|--------|------|--------|
| GET | `/movies/` | public |
| GET | `/movies/{movie_id}/` | public |
| POST | `/movies/` | moderator |
| PATCH | `/movies/{movie_id}/` | moderator |
| DELETE | `/movies/{movie_id}/` | moderator |
| GET | `/genres/` | public |

### `GET /movies/`

The main catalog endpoint. All parameters are optional and combine freely.

| Parameter | Type | Meaning |
|-----------|------|---------|
| `page` | int ≥ 1 | Page number, default `1` |
| `per_page` | int 1–20 | Items per page, default `10` |
| `year` | int | Exact release year |
| `year_from`, `year_to` | int | Inclusive release-year range |
| `imdb_min`, `imdb_max` | float 0–10 | IMDb rating range |
| `price_max` | float | Highest acceptable price |
| `genre` | string | Exact genre name, case-insensitive |
| `search` | string | Matches title, description, star or director |
| `sort_by` | `id`,`price`,`year`,`imdb`,`votes`,`name` | Sort column, default `id` |
| `order` | `asc`, `desc` | Sort direction, default `desc` |

```
GET /api/v1/cinema/movies/?year_from=1990&imdb_min=8&sort_by=price&order=asc
```

Returns the page plus `total_items`, `total_pages` and `prev_page`/`next_page`
links. Returns `404` when nothing matches or the page is past the end, and
`422` when pagination values are out of range.

### `POST /movies/` · `PATCH /movies/{movie_id}/`

**What they do:** create or partially update a movie. Genres, directors, stars
and the certification are given **by name**, not by id, and any that do not
exist yet are created automatically — a client never has to look identifiers up
first.

```json
{
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
  "stars": ["Amy Adams"]
}
```

`PATCH` writes only the fields present in the body. Supplying `genres`,
`directors` or `stars` **replaces** that list rather than adding to it.
`409` is returned when the name, year and duration together match an existing
movie — that triple is the uniqueness rule for a film.

### `DELETE /movies/{movie_id}/`

**What it does:** removes a movie, unless at least one **paid** order contains
it. In that case it returns `400`, because deleting the row would corrupt the
purchase history of the customers who bought it.

### `GET /genres/`

Returns every genre with the number of movies in it, so a genre menu renders
from a single request:

```json
[{ "id": 3, "name": "Drama", "movie_count": 12 }]
```

## Cart — `/api/v1/shop`

| Method | Path | Access |
|--------|------|--------|
| GET | `/cart/` | signed in |
| POST | `/cart/items/` | signed in |
| DELETE | `/cart/items/{movie_id}/` | signed in |
| DELETE | `/cart/` | signed in |
| GET | `/users/{user_id}/cart/` | moderator |

### `POST /cart/items/`

```json
{ "movie_id": 7 }
```

**Two guards, both returning `400`:** a movie the user has already bought
cannot be added again, and a movie already in the cart cannot be added twice.
The response is the whole cart, so the client does not need a follow-up
request. Each line carries the title, year, price and genres, and the payload
includes the running `total_amount`.

### `GET /users/{user_id}/cart/`

**What it does:** lets a moderator or admin look inside somebody else's cart.
Intended for support work — for example, explaining why a movie is still
referenced when a moderator tries to delete it. Returns `403` for regular
users.

## Orders — `/api/v1/shop`

| Method | Path | Access |
|--------|------|--------|
| POST | `/orders/` | signed in |
| GET | `/orders/` | signed in |
| GET | `/orders/{order_id}/` | signed in |
| POST | `/orders/{order_id}/cancel/` | signed in |
| GET | `/admin/orders/` | moderator |

### `POST /orders/`

**What it does:** converts the cart into a pending order and empties the cart.
Takes no body.

Rather than failing outright when part of the cart cannot be ordered, it skips
those movies and reports them back:

```json
{
  "order": { "id": 4, "status": "pending", "total_amount": "15.50", "items": [] },
  "excluded": ["Heat (already purchased)"]
}
```

A movie is excluded when the user already owns it, or when it is already part
of another unpaid order. The price of each remaining movie is copied onto the
order item, so a later price change never rewrites an existing order.

The request fails with `400` only when the cart is empty, or when nothing in
it survives those checks.

### `POST /orders/{order_id}/cancel/`

Cancels an unpaid order. A `paid` order returns `400` and would need a refund
instead; an already-cancelled order also returns `400`. Reading or cancelling
somebody else's order returns `404` rather than `403`, so the endpoint does not
confirm that the order exists.

### `GET /admin/orders/`

**What it does:** lists orders across all customers, for moderators and admins.

| Parameter | Type | Meaning |
|-----------|------|---------|
| `user_id` | int | Only this customer |
| `order_status` | `pending`, `paid`, `canceled` | Only this status |
| `date_from`, `date_to` | date `YYYY-MM-DD` | Inclusive creation-date range |

```
GET /api/v1/shop/admin/orders/?order_status=paid&date_from=2026-01-01
```

## Scheduled work

Celery beat runs `tasks.tokens.purge_expired_tokens` at the top of every hour.
It deletes activation and password-reset tokens whose expiry has passed.

This is not just tidiness: `user_id` is unique on both token tables, so an
expired row would otherwise stand in the way of issuing the user a fresh token.
