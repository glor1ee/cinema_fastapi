class StubEmailSender:

    def __init__(self) -> None:
        self.activation_emails: list[tuple[str, str]] = []
        self.activation_complete_emails: list[tuple[str, str]] = []
        self.password_reset_emails: list[tuple[str, str]] = []
        self.password_reset_complete_emails: list[tuple[str, str]] = []

    async def send_activation_email(self, email: str, activation_link: str) -> None:
        self.activation_emails.append((email, activation_link))

    async def send_activation_complete_email(self, email: str, login_link: str) -> None:
        self.activation_complete_emails.append((email, login_link))

    async def send_password_reset_email(self, email: str, reset_link: str) -> None:
        self.password_reset_emails.append((email, reset_link))

    async def send_password_reset_complete_email(self, email: str, login_link: str) -> None:
        self.password_reset_complete_emails.append((email, login_link))
