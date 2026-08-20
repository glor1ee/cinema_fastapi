from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class CartItemSchema(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: int
    movie_id: int
    name: str
    year: int
    price: Decimal
    genres: list[str]
    added_at: datetime


class CartSchema(BaseModel):
    id: int
    user_id: int
    items: list[CartItemSchema]
    total_amount: Decimal


class CartItemCreateSchema(BaseModel):
    movie_id: int


class MessageResponseSchema(BaseModel):
    message: str
