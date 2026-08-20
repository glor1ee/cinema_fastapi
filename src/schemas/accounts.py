from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from database import accounts_validators
from database.models.accounts import UserGroupEnum


class BaseEmailSchema(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class UserRegistrationRequestSchema(BaseEmailSchema):
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return accounts_validators.validate_password_strength(value)


class UserRegistrationResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr


class UserActivationRequestSchema(BaseEmailSchema):
    token: str


class ResendActivationRequestSchema(BaseEmailSchema):
    pass


class PasswordResetRequestSchema(BaseEmailSchema):
    pass


class PasswordResetCompleteRequestSchema(BaseEmailSchema):
    token: str
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return accounts_validators.validate_password_strength(value)


class PasswordChangeRequestSchema(BaseModel):

    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return accounts_validators.validate_password_strength(value)


class UserLoginRequestSchema(BaseEmailSchema):
    password: str


class UserLoginResponseSchema(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefreshRequestSchema(BaseModel):
    refresh_token: str


class TokenRefreshResponseSchema(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LogoutRequestSchema(BaseModel):
    refresh_token: str


class MessageResponseSchema(BaseModel):
    message: str


class UserGroupUpdateRequestSchema(BaseModel):

    group: UserGroupEnum


class UserDetailSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    is_active: bool
    group: UserGroupEnum

    @field_validator("group", mode="before")
    @classmethod
    def unwrap_group(cls, value: object) -> object:
        return getattr(value, "name", value)
