class BaseSecurityError(Exception):

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "A security error occurred.")


class TokenExpiredError(BaseSecurityError):

    def __init__(self, message: str = "Token has expired.") -> None:
        super().__init__(message)


class InvalidTokenError(BaseSecurityError):

    def __init__(self, message: str = "Invalid token.") -> None:
        super().__init__(message)
