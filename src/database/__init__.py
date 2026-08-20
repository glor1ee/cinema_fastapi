import os

from database.models import (
    ActivationTokenModel,
    Base,
    CartItemModel,
    CartModel,
    CertificationModel,
    DirectorModel,
    GenderEnum,
    GenreModel,
    MovieModel,
    MoviesDirectorsModel,
    MoviesGenresModel,
    MoviesStarsModel,
    OrderItemModel,
    OrderModel,
    OrderStatusEnum,
    PasswordResetTokenModel,
    RefreshTokenModel,
    StarModel,
    UserGroupEnum,
    UserGroupModel,
    UserModel,
    UserProfileModel,
)
from database.session_sqlite import reset_sqlite_database as reset_database
from database.validators import accounts as accounts_validators

environment = os.getenv("ENVIRONMENT", "developing")

if environment == "testing":
    from database.session_sqlite import (  # noqa: F401
        get_sqlite_db as get_db,
        get_sqlite_db_contextmanager as get_db_contextmanager,
    )
else:
    from database.session_postgresql import (  # noqa: F401
        get_postgresql_db as get_db,
        get_postgresql_db_contextmanager as get_db_contextmanager,
    )

__all__ = [
    "Base",
    "ActivationTokenModel",
    "CartItemModel",
    "CartModel",
    "CertificationModel",
    "DirectorModel",
    "GenderEnum",
    "GenreModel",
    "MovieModel",
    "MoviesDirectorsModel",
    "MoviesGenresModel",
    "MoviesStarsModel",
    "OrderItemModel",
    "OrderModel",
    "OrderStatusEnum",
    "PasswordResetTokenModel",
    "RefreshTokenModel",
    "StarModel",
    "UserGroupEnum",
    "UserGroupModel",
    "UserModel",
    "UserProfileModel",
    "accounts_validators",
    "get_db",
    "get_db_contextmanager",
    "reset_database",
]
