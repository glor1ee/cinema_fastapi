import re

import email_validator

SPECIAL_CHARACTERS = "@$!%*?&#"


def validate_password_strength(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must contain at least 8 characters.")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter.")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one digit.")
    if not re.search(rf"[{re.escape(SPECIAL_CHARACTERS)}]", password):
        raise ValueError(
            "Password must contain at least one special character: "
            f"{', '.join(SPECIAL_CHARACTERS)}."
        )
    return password


def validate_email(user_email: str) -> str:
    try:
        email_info = email_validator.validate_email(user_email, check_deliverability=False)
    except email_validator.EmailNotValidError as error:
        raise ValueError(str(error)) from error
    return email_info.normalized
