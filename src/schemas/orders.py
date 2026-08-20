from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from database.models.orders import OrderStatusEnum


class OrderItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    movie_id: int
    name: str
    price_at_order: Decimal


class OrderSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
    status: OrderStatusEnum
    total_amount: Decimal
    items: list[OrderItemSchema]


class OrderCreateResponseSchema(BaseModel):

    order: OrderSchema
    excluded: list[str] = []


class MessageResponseSchema(BaseModel):
    message: str
