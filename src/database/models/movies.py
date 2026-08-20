import uuid as uuid_lib
from decimal import Decimal

from sqlalchemy import (
    DECIMAL,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base

MoviesGenresModel = Table(
    "movie_genres",
    Base.metadata,
    Column(
        "movie_id",
        ForeignKey("movies.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    Column(
        "genre_id",
        ForeignKey("genres.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
)

MoviesDirectorsModel = Table(
    "movie_directors",
    Base.metadata,
    Column(
        "movie_id",
        ForeignKey("movies.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    Column(
        "director_id",
        ForeignKey("directors.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
)

MoviesStarsModel = Table(
    "movie_stars",
    Base.metadata,
    Column(
        "movie_id",
        ForeignKey("movies.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    Column(
        "star_id",
        ForeignKey("stars.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
)


class GenreModel(Base):
    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)

    movies: Mapped[list["MovieModel"]] = relationship(
        "MovieModel", secondary=MoviesGenresModel, back_populates="genres"
    )

    def __repr__(self) -> str:
        return f"<GenreModel(id={self.id}, name={self.name})>"


class StarModel(Base):
    __tablename__ = "stars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    movies: Mapped[list["MovieModel"]] = relationship(
        "MovieModel", secondary=MoviesStarsModel, back_populates="stars"
    )

    def __repr__(self) -> str:
        return f"<StarModel(id={self.id}, name={self.name})>"


class DirectorModel(Base):
    __tablename__ = "directors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    movies: Mapped[list["MovieModel"]] = relationship(
        "MovieModel", secondary=MoviesDirectorsModel, back_populates="directors"
    )

    def __repr__(self) -> str:
        return f"<DirectorModel(id={self.id}, name={self.name})>"


class CertificationModel(Base):
    __tablename__ = "certifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    movies: Mapped[list["MovieModel"]] = relationship("MovieModel", back_populates="certification")

    def __repr__(self) -> str:
        return f"<CertificationModel(id={self.id}, name={self.name})>"


class MovieModel(Base):
    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid_lib.uuid4()),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    time: Mapped[int] = mapped_column(Integer, nullable=False)
    imdb: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    votes: Mapped[int] = mapped_column(Integer, nullable=False)
    meta_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)

    certification_id: Mapped[int] = mapped_column(
        ForeignKey("certifications.id", ondelete="RESTRICT"), nullable=False
    )
    certification: Mapped["CertificationModel"] = relationship(
        "CertificationModel", back_populates="movies"
    )

    genres: Mapped[list["GenreModel"]] = relationship(
        "GenreModel", secondary=MoviesGenresModel, back_populates="movies"
    )
    directors: Mapped[list["DirectorModel"]] = relationship(
        "DirectorModel", secondary=MoviesDirectorsModel, back_populates="movies"
    )
    stars: Mapped[list["StarModel"]] = relationship(
        "StarModel", secondary=MoviesStarsModel, back_populates="movies"
    )

    __table_args__ = (UniqueConstraint("name", "year", "time", name="unique_movie_constraint"),)

    def __repr__(self) -> str:
        return f"<MovieModel(id={self.id}, name={self.name}, year={self.year})>"
