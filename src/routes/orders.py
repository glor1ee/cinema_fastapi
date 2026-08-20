from datetime import date, datetime, time, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
from schemas.orders import (
    OrderCreateResponseSchema,
    OrderItemSchema,
    OrderSchema,
)

router = APIRouter()


def _serialize_order(order: OrderModel) -> OrderSchema:
    return OrderSchema(
        id=order.id,
        user_id=order.user_id,
        created_at=order.created_at,
        status=order.status,
        total_amount=order.total_amount,
        items=[
            OrderItemSchema(
                id=item.id,
                movie_id=item.movie_id,
                name=item.movie.name,
                price_at_order=item.price_at_order,
            )
            for item in order.items
        ],
    )


async def _load_order(db: AsyncSession, order_id: int) -> OrderModel | None:
    result = await db.execute(
        select(OrderModel)
        .options(selectinload(OrderModel.items).selectinload(OrderItemModel.movie))
        .where(OrderModel.id == order_id)
    )
    return result.scalars().first()


async def _load_existing_order(db: AsyncSession, order_id: int) -> OrderModel:
    order = await _load_order(db, order_id)
    if order is None:  # pragma: no cover - the row was just written
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
    return order


async def _movies_already_owned(db: AsyncSession, user_id: int) -> set[int]:
    result = await db.execute(
        select(OrderItemModel.movie_id)
        .join(OrderModel, OrderItemModel.order_id == OrderModel.id)
        .where(OrderModel.user_id == user_id, OrderModel.status == OrderStatusEnum.PAID)
    )
    return set(result.scalars().all())


async def _movies_in_pending_orders(db: AsyncSession, user_id: int) -> set[int]:
    result = await db.execute(
        select(OrderItemModel.movie_id)
        .join(OrderModel, OrderItemModel.order_id == OrderModel.id)
        .where(OrderModel.user_id == user_id, OrderModel.status == OrderStatusEnum.PENDING)
    )
    return set(result.scalars().all())


@router.post(
    "/orders/",
    response_model=OrderCreateResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Turn your cart into an order",
    description=(
        "Creates a pending order from the cart and empties it.\n\n"
        "Movies are skipped rather than failing the whole request when the user "
        "already owns them or they are already part of another pending order. "
        "Skipped titles come back in `excluded`. The price of each movie is "
        "copied onto the order item, so later price changes do not rewrite "
        "history.\n\n"
        "The request fails only when the cart is empty, or when nothing at all "
        "survives the checks."
    ),
    responses={
        400: {"description": "The cart is empty, or nothing in it can be ordered."},
        401: {"description": "Not signed in."},
    },
)
async def place_order(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> OrderCreateResponseSchema:
    cart_result = await db.execute(
        select(CartModel)
        .options(selectinload(CartModel.items).selectinload(CartItemModel.movie))
        .where(CartModel.user_id == current_user.id)
    )
    cart = cart_result.scalars().first()

    if cart is None or not cart.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Your cart is empty.")

    owned = await _movies_already_owned(db, current_user.id)
    pending = await _movies_in_pending_orders(db, current_user.id)

    payable: list[MovieModel] = []
    excluded: list[str] = []

    for item in cart.items:
        movie = item.movie
        if movie is None:
            continue
        if movie.id in owned:
            excluded.append(f"{movie.name} (already purchased)")
        elif movie.id in pending:
            excluded.append(f"{movie.name} (already in a pending order)")
        else:
            payable.append(movie)

    if not payable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="None of the movies in your cart can be ordered.",
        )

    order = OrderModel(
        user_id=current_user.id,
        status=OrderStatusEnum.PENDING,
        total_amount=sum((movie.price for movie in payable), Decimal("0.00")),
    )
    db.add(order)
    await db.flush()

    for movie in payable:
        db.add(OrderItemModel(order_id=order.id, movie_id=movie.id, price_at_order=movie.price))

    await db.execute(delete(CartItemModel).where(CartItemModel.cart_id == cart.id))
    await db.commit()

    return OrderCreateResponseSchema(
        order=_serialize_order(await _load_existing_order(db, order.id)),
        excluded=excluded,
    )


@router.get(
    "/orders/",
    response_model=list[OrderSchema],
    summary="List your orders",
    description="Returns the signed-in user's orders, newest first.",
    responses={401: {"description": "Not signed in."}},
)
async def list_orders(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> list[OrderSchema]:
    result = await db.execute(
        select(OrderModel)
        .options(selectinload(OrderModel.items).selectinload(OrderItemModel.movie))
        .where(OrderModel.user_id == current_user.id)
        .order_by(OrderModel.created_at.desc(), OrderModel.id.desc())
    )
    return [_serialize_order(order) for order in result.scalars().all()]


@router.get(
    "/orders/{order_id}/",
    response_model=OrderSchema,
    summary="Order details",
    description="Returns one of your own orders with its items and total.",
    responses={
        401: {"description": "Not signed in."},
        404: {"description": "No such order, or it belongs to someone else."},
    },
)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> OrderSchema:
    order = await _load_order(db, order_id)
    if order is None or order.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
    return _serialize_order(order)


@router.post(
    "/orders/{order_id}/cancel/",
    response_model=OrderSchema,
    summary="Cancel an order",
    description=(
        "Cancels an order that has not been paid for. A paid order cannot be "
        "cancelled here; it would need a refund instead."
    ),
    responses={
        400: {"description": "The order is already paid or already cancelled."},
        401: {"description": "Not signed in."},
        404: {"description": "No such order, or it belongs to someone else."},
    },
)
async def cancel_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> OrderSchema:
    order = await _load_order(db, order_id)
    if order is None or order.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    if order.status == OrderStatusEnum.PAID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A paid order cannot be cancelled. Request a refund instead.",
        )
    if order.status == OrderStatusEnum.CANCELED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This order has already been cancelled.",
        )

    order.status = OrderStatusEnum.CANCELED
    await db.commit()

    return _serialize_order(await _load_existing_order(db, order_id))


@router.get(
    "/admin/orders/",
    response_model=list[OrderSchema],
    summary="Browse every order",
    description=(
        "Moderators and admins only. Optional filters: `user_id` for one "
        "customer, `order_status` for `pending`, `paid` or `canceled`, and "
        "`date_from`/`date_to` for a creation-date range (inclusive)."
    ),
    responses={403: {"description": "Caller is not a moderator or admin."}},
)
async def list_all_orders(
    user_id: int | None = Query(None, description="Only this customer"),
    order_status: OrderStatusEnum | None = Query(None, description="Only this status"),
    date_from: date | None = Query(None, description="Created on or after this date"),
    date_to: date | None = Query(None, description="Created on or before this date"),
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(require_moderator),
) -> list[OrderSchema]:
    stmt = select(OrderModel).options(
        selectinload(OrderModel.items).selectinload(OrderItemModel.movie)
    )

    if user_id is not None:
        stmt = stmt.where(OrderModel.user_id == user_id)
    if order_status is not None:
        stmt = stmt.where(OrderModel.status == order_status)
    if date_from is not None:
        stmt = stmt.where(
            OrderModel.created_at >= datetime.combine(date_from, time.min, timezone.utc)
        )
    if date_to is not None:
        stmt = stmt.where(
            OrderModel.created_at <= datetime.combine(date_to, time.max, timezone.utc)
        )

    result = await db.execute(stmt.order_by(OrderModel.created_at.desc(), OrderModel.id.desc()))
    return [_serialize_order(order) for order in result.scalars().all()]
