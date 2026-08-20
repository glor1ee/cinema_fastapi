from typing import Literal, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from config import require_moderator
from database import (
    CartItemModel,
    CertificationModel,
    DirectorModel,
    GenreModel,
    MovieModel,
    OrderItemModel,
    StarModel,
    UserModel,
    get_db,
)
from schemas.movies import (
    GenreWithCountSchema,
    MovieCreateSchema,
    MovieDetailSchema,
    MovieListItemSchema,
    MovieListResponseSchema,
    MovieUpdateSchema,
)

router = APIRouter()

SortField = Literal["id", "price", "year", "imdb", "votes", "name"]
SortOrder = Literal["asc", "desc"]

_SORT_COLUMNS = {
    "id": MovieModel.id,
    "price": MovieModel.price,
    "year": MovieModel.year,
    "imdb": MovieModel.imdb,
    "votes": MovieModel.votes,
    "name": MovieModel.name,
}

_DETAIL_LOADERS = (
    joinedload(MovieModel.certification),
    selectinload(MovieModel.genres),
    selectinload(MovieModel.directors),
    selectinload(MovieModel.stars),
)


async def _get_or_create(db: AsyncSession, model, name: str):
    result = await db.execute(select(model).where(model.name == name))
    instance = result.scalars().first()
    if instance is None:
        instance = model(name=name)
        db.add(instance)
        await db.flush()
    return instance


async def _resolve_related(db: AsyncSession, model, names: Sequence[str]) -> list:
    resolved = []
    for name in names:
        cleaned = name.strip()
        if cleaned:
            resolved.append(await _get_or_create(db, model, cleaned))
    return resolved


async def _load_movie_or_404(db: AsyncSession, movie_id: int) -> MovieModel:
    result = await db.execute(
        select(MovieModel).options(*_DETAIL_LOADERS).where(MovieModel.id == movie_id)
    )
    movie = result.scalars().first()
    if movie is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie with the given ID was not found.",
        )
    return movie


def _apply_filters(
    stmt: Select,
    year: int | None,
    year_from: int | None,
    year_to: int | None,
    imdb_min: float | None,
    imdb_max: float | None,
    price_max: float | None,
    genre: str | None,
    search: str | None,
) -> Select:
    if year is not None:
        stmt = stmt.where(MovieModel.year == year)
    if year_from is not None:
        stmt = stmt.where(MovieModel.year >= year_from)
    if year_to is not None:
        stmt = stmt.where(MovieModel.year <= year_to)
    if imdb_min is not None:
        stmt = stmt.where(MovieModel.imdb >= imdb_min)
    if imdb_max is not None:
        stmt = stmt.where(MovieModel.imdb <= imdb_max)
    if price_max is not None:
        stmt = stmt.where(MovieModel.price <= price_max)
    if genre is not None:
        stmt = stmt.where(MovieModel.genres.any(GenreModel.name.ilike(genre)))
    if search is not None:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                MovieModel.name.ilike(pattern),
                MovieModel.description.ilike(pattern),
                MovieModel.stars.any(StarModel.name.ilike(pattern)),
                MovieModel.directors.any(DirectorModel.name.ilike(pattern)),
            )
        )
    return stmt


@router.get(
    "/movies/",
    response_model=MovieListResponseSchema,
    summary="Browse the movie catalog",
    description=(
        "Returns a page of movies.\n\n"
        "**Pagination** — `page` (from 1) and `per_page` (1-20).\n\n"
        "**Filtering** — `year` for an exact year, or `year_from`/`year_to` for a "
        "range; `imdb_min`/`imdb_max` for the rating; `price_max` for the price; "
        "`genre` for an exact genre name.\n\n"
        "**Search** — `search` matches the title, the description, a star's name "
        "or a director's name, case-insensitively.\n\n"
        "**Sorting** — `sort_by` accepts `price`, `year`, `imdb`, `votes` or "
        "`name`, and `order` accepts `asc` or `desc`."
    ),
    responses={404: {"description": "No movies matched the request."}},
)
async def list_movies(
    page: int = Query(1, ge=1, description="Page number, starting at 1"),
    per_page: int = Query(10, ge=1, le=20, description="Movies per page"),
    year: int | None = Query(None, description="Exact release year"),
    year_from: int | None = Query(None, description="Earliest release year"),
    year_to: int | None = Query(None, description="Latest release year"),
    imdb_min: float | None = Query(None, ge=0, le=10, description="Lowest IMDb rating"),
    imdb_max: float | None = Query(None, ge=0, le=10, description="Highest IMDb rating"),
    price_max: float | None = Query(None, ge=0, description="Highest price"),
    genre: str | None = Query(None, description="Exact genre name"),
    search: str | None = Query(None, description="Title, description, star or director"),
    sort_by: SortField = Query("id", description="Field to sort by; defaults to newest first"),
    order: SortOrder = Query("desc", description="Sort direction"),
    db: AsyncSession = Depends(get_db),
) -> MovieListResponseSchema:
    base = _apply_filters(
        select(MovieModel),
        year,
        year_from,
        year_to,
        imdb_min,
        imdb_max,
        price_max,
        genre,
        search,
    )

    count_stmt = _apply_filters(
        select(func.count(MovieModel.id)),
        year,
        year_from,
        year_to,
        imdb_min,
        imdb_max,
        price_max,
        genre,
        search,
    )
    total_items = (await db.execute(count_stmt)).scalar_one()

    if not total_items:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No movies found.")

    total_pages = (total_items + per_page - 1) // per_page
    if page > total_pages:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No movies found.")

    column = _SORT_COLUMNS.get(sort_by, MovieModel.id)
    ordering = column.asc() if order == "asc" else column.desc()

    result = await db.execute(base.order_by(ordering).offset((page - 1) * per_page).limit(per_page))
    movies = result.scalars().all()

    def page_link(target: int) -> str:
        return f"/movies/?page={target}&per_page={per_page}"

    return MovieListResponseSchema(
        movies=[MovieListItemSchema.model_validate(movie) for movie in movies],
        prev_page=page_link(page - 1) if page > 1 else None,
        next_page=page_link(page + 1) if page < total_pages else None,
        total_pages=total_pages,
        total_items=total_items,
    )


@router.get(
    "/genres/",
    response_model=list[GenreWithCountSchema],
    summary="List genres with movie counts",
    description=(
        "Returns every genre together with how many movies belong to it, so a "
        "client can render the genre menu in one request."
    ),
)
async def list_genres(db: AsyncSession = Depends(get_db)) -> list[GenreWithCountSchema]:
    result = await db.execute(
        select(GenreModel.id, GenreModel.name, func.count(MovieModel.id))
        .outerjoin(GenreModel.movies)
        .group_by(GenreModel.id, GenreModel.name)
        .order_by(GenreModel.name)
    )
    return [
        GenreWithCountSchema(id=row[0], name=row[1], movie_count=row[2]) for row in result.all()
    ]


@router.get(
    "/movies/{movie_id}/",
    response_model=MovieDetailSchema,
    summary="Movie details",
    description="Returns one movie with its certification, genres, directors and stars.",
    responses={404: {"description": "No movie with this ID."}},
)
async def get_movie(movie_id: int, db: AsyncSession = Depends(get_db)) -> MovieDetailSchema:
    movie = await _load_movie_or_404(db, movie_id)
    return MovieDetailSchema.model_validate(movie)


@router.post(
    "/movies/",
    response_model=MovieDetailSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create a movie",
    description=(
        "Moderators and admins only. Genres, directors, stars and the "
        "certification are passed by name and created on demand when they are "
        "not in the database yet."
    ),
    responses={
        403: {"description": "Caller is not a moderator or admin."},
        409: {"description": "This name, year and duration already exist."},
    },
)
async def create_movie(
    movie_data: MovieCreateSchema,
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(require_moderator),
) -> MovieDetailSchema:
    duplicate = await db.execute(
        select(MovieModel).where(
            MovieModel.name == movie_data.name,
            MovieModel.year == movie_data.year,
            MovieModel.time == movie_data.time,
        )
    )
    if duplicate.scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A movie '{movie_data.name}' released in {movie_data.year} with a "
                f"runtime of {movie_data.time} minutes already exists."
            ),
        )

    certification = await _get_or_create(db, CertificationModel, movie_data.certification)

    movie = MovieModel(
        name=movie_data.name,
        year=movie_data.year,
        time=movie_data.time,
        imdb=movie_data.imdb,
        votes=movie_data.votes,
        meta_score=movie_data.meta_score,
        gross=movie_data.gross,
        description=movie_data.description,
        price=movie_data.price,
        certification=certification,
        genres=await _resolve_related(db, GenreModel, movie_data.genres),
        directors=await _resolve_related(db, DirectorModel, movie_data.directors),
        stars=await _resolve_related(db, StarModel, movie_data.stars),
    )
    db.add(movie)

    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A movie with these details already exists.",
        ) from error

    return MovieDetailSchema.model_validate(await _load_movie_or_404(db, movie.id))


@router.patch(
    "/movies/{movie_id}/",
    response_model=MovieDetailSchema,
    summary="Update a movie",
    description=(
        "Moderators and admins only. Only the fields present in the body are "
        "changed; supplying `genres`, `directors` or `stars` replaces that list "
        "entirely."
    ),
    responses={
        403: {"description": "Caller is not a moderator or admin."},
        404: {"description": "No movie with this ID."},
    },
)
async def update_movie(
    movie_id: int,
    movie_data: MovieUpdateSchema,
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(require_moderator),
) -> MovieDetailSchema:
    movie = await _load_movie_or_404(db, movie_id)
    payload = movie_data.model_dump(exclude_unset=True)

    if "certification" in payload and payload["certification"] is not None:
        movie.certification = await _get_or_create(
            db, CertificationModel, payload.pop("certification")
        )
    else:
        payload.pop("certification", None)

    for field, model in (
        ("genres", GenreModel),
        ("directors", DirectorModel),
        ("stars", StarModel),
    ):
        if field in payload and payload[field] is not None:
            setattr(movie, field, await _resolve_related(db, model, payload.pop(field)))
        else:
            payload.pop(field, None)

    for field, value in payload.items():
        if value is not None:
            setattr(movie, field, value)

    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A movie with these details already exists.",
        ) from error

    return MovieDetailSchema.model_validate(await _load_movie_or_404(db, movie_id))


@router.delete(
    "/movies/{movie_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a movie",
    description=(
        "Moderators and admins only. A movie referenced by any order, at any "
        "status, or sitting in someone's cart cannot be deleted: the foreign "
        "key from order items cascades, and deleting it anyway would silently "
        "corrupt that order's history."
    ),
    responses={
        400: {"description": "The movie is referenced by an order or a cart."},
        403: {"description": "Caller is not a moderator or admin."},
        404: {"description": "No movie with this ID."},
    },
)
async def delete_movie(
    movie_id: int,
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(require_moderator),
) -> None:
    movie = await _load_movie_or_404(db, movie_id)

    ordered = await db.execute(
        select(func.count(OrderItemModel.id)).where(OrderItemModel.movie_id == movie_id)
    )
    if ordered.scalar_one() > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This movie is part of an order and cannot be deleted.",
        )

    in_cart = await db.execute(
        select(func.count(CartItemModel.id)).where(CartItemModel.movie_id == movie_id)
    )
    if in_cart.scalar_one() > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This movie is in a cart and cannot be deleted.",
        )

    await db.delete(movie)
    await db.commit()
