from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import get_current_user, require_moderator
from database import (
    CartItemModel,
    CartModel,
    MovieModel,
    OrderItemModel,
    OrderModel,
    OrderStatusEnum,
    UserModel,
    get_db,
)
from schemas.cart import (
    CartItemCreateSchema,
    CartItemSchema,
    CartSchema,
    MessageResponseSchema,
)

router = APIRouter()


async def _get_or_create_cart(db: AsyncSession, user_id: int) -> CartModel:
    result = await db.execute(select(CartModel).where(CartModel.user_id == user_id))
    cart = result.scalars().first()
    if cart is None:
        cart = CartModel(user_id=user_id)
        db.add(cart)
        await db.flush()
    return cart


async def _load_cart_with_items(db: AsyncSession, cart_id: int) -> CartModel:
    result = await db.execute(
        select(CartModel)
        .options(
            selectinload(CartModel.items)
            .selectinload(CartItemModel.movie)
            .selectinload(MovieModel.genres)
        )
        .where(CartModel.id == cart_id)
    )
    cart = result.scalars().first()
    if cart is None:  # pragma: no cover - the caller just created this cart
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart not found.")
    return cart


async def _has_purchased(db: AsyncSession, user_id: int, movie_id: int) -> bool:
    result = await db.execute(
        select(OrderItemModel.id)
        .join(OrderModel, OrderItemModel.order_id == OrderModel.id)
        .where(
            OrderModel.user_id == user_id,
            OrderItemModel.movie_id == movie_id,
            OrderModel.status == OrderStatusEnum.PAID,
        )
        .limit(1)
    )
    return result.scalars().first() is not None


def _serialize_cart(cart: CartModel) -> CartSchema:
    items = [
        CartItemSchema(
            id=item.id,
            movie_id=item.movie.id,
            name=item.movie.name,
            year=item.movie.year,
            price=item.movie.price,
            genres=[genre.name for genre in item.movie.genres],
            added_at=item.added_at,
        )
        for item in cart.items
    ]
    total = sum((item.price for item in items), Decimal("0.00"))
    return CartSchema(id=cart.id, user_id=cart.user_id, items=items, total_amount=total)


@router.get(
    "/cart/",
    response_model=CartSchema,
    summary="View your cart",
    description=(
        "Returns the signed-in user's cart. Each entry carries the title, "
        "release year, price and genres, and the response includes the running "
        "total. An empty cart is returned as an empty list, not an error."
    ),
    responses={401: {"description": "Not signed in."}},
)
async def view_cart(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> CartSchema:
    cart = await _get_or_create_cart(db, current_user.id)
    await db.commit()
    return _serialize_cart(await _load_cart_with_items(db, cart.id))


@router.post(
    "/cart/items/",
    response_model=CartSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Add a movie to your cart",
    description=(
        "Adds one movie to the cart. A movie the user already bought is refused, "
        "and so is a movie that is already sitting in the cart."
    ),
    responses={
        400: {"description": "Already purchased, or already in the cart."},
        401: {"description": "Not signed in."},
        404: {"description": "No movie with this ID."},
    },
)
async def add_to_cart(
    payload: CartItemCreateSchema,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> CartSchema:
    movie = await db.get(MovieModel, payload.movie_id)
    if movie is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie with the given ID was not found.",
        )

    if await _has_purchased(db, current_user.id, movie.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already purchased this movie.",
        )

    cart = await _get_or_create_cart(db, current_user.id)

    existing = await db.execute(
        select(CartItemModel).where(
            CartItemModel.cart_id == cart.id, CartItemModel.movie_id == movie.id
        )
    )
    if existing.scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This movie is already in your cart.",
        )

    db.add(CartItemModel(cart_id=cart.id, movie_id=movie.id))
    await db.commit()

    return _serialize_cart(await _load_cart_with_items(db, cart.id))


@router.delete(
    "/cart/items/{movie_id}/",
    response_model=CartSchema,
    summary="Remove a movie from your cart",
    responses={
        401: {"description": "Not signed in."},
        404: {"description": "That movie is not in your cart."},
    },
)
async def remove_from_cart(
    movie_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> CartSchema:
    cart = await _get_or_create_cart(db, current_user.id)

    result = await db.execute(
        select(CartItemModel).where(
            CartItemModel.cart_id == cart.id, CartItemModel.movie_id == movie_id
        )
    )
    item = result.scalars().first()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="This movie is not in your cart."
        )

    await db.delete(item)
    await db.commit()

    return _serialize_cart(await _load_cart_with_items(db, cart.id))


@router.delete(
    "/cart/",
    response_model=MessageResponseSchema,
    summary="Empty your cart",
    description="Removes every item at once. Succeeds even when the cart is already empty.",
    responses={401: {"description": "Not signed in."}},
)
async def clear_cart(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> MessageResponseSchema:
    cart = await _get_or_create_cart(db, current_user.id)
    await db.execute(delete(CartItemModel).where(CartItemModel.cart_id == cart.id))
    await db.commit()
    return MessageResponseSchema(message="Cart cleared.")


@router.get(
    "/users/{user_id}/cart/",
    response_model=CartSchema,
    summary="Inspect another user's cart",
    description=(
        "Moderators and admins only. Intended for support and analytics, for "
        "example when checking why a movie cannot be deleted."
    ),
    responses={
        403: {"description": "Caller is not a moderator or admin."},
        404: {"description": "That user has no cart."},
    },
)
async def view_user_cart(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(require_moderator),
) -> CartSchema:
    result = await db.execute(select(CartModel).where(CartModel.user_id == user_id))
    cart = result.scalars().first()
    if cart is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This user has no cart.")
    return _serialize_cart(await _load_cart_with_items(db, cart.id))
