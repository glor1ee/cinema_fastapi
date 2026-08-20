from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NamedEntitySchema(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class GenreWithCountSchema(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    movie_count: int


class MovieListItemSchema(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    year: int
    imdb: float
    price: Decimal


class MovieListResponseSchema(BaseModel):
    movies: list[MovieListItemSchema]
    prev_page: str | None
    next_page: str | None
    total_pages: int
    total_items: int


class MovieDetailSchema(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: str
    name: str
    year: int
    time: int
    imdb: float
    votes: int
    meta_score: float | None
    gross: float | None
    description: str
    price: Decimal
    certification: NamedEntitySchema
    genres: list[NamedEntitySchema]
    directors: list[NamedEntitySchema]
    stars: list[NamedEntitySchema]


class MovieCreateSchema(BaseModel):

    name: str = Field(max_length=255)
    year: int = Field(ge=1888, le=2100)
    time: int = Field(gt=0, description="Duration in minutes")
    imdb: float = Field(ge=0, le=10)
    votes: int = Field(ge=0)
    meta_score: float | None = Field(default=None, ge=0, le=100)
    gross: float | None = Field(default=None, ge=0)
    description: str
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    certification: str
    genres: list[str] = Field(default_factory=list)
    directors: list[str] = Field(default_factory=list)
    stars: list[str] = Field(default_factory=list)

    @field_validator("name", "certification")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Field must not be empty or whitespace only.")
        return value.strip()


class MovieUpdateSchema(BaseModel):

    name: str | None = Field(default=None, max_length=255)
    year: int | None = Field(default=None, ge=1888, le=2100)
    time: int | None = Field(default=None, gt=0)
    imdb: float | None = Field(default=None, ge=0, le=10)
    votes: int | None = Field(default=None, ge=0)
    meta_score: float | None = Field(default=None, ge=0, le=100)
    gross: float | None = Field(default=None, ge=0)
    description: str | None = None
    price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    certification: str | None = None
    genres: list[str] | None = None
    directors: list[str] | None = None
    stars: list[str] | None = None
