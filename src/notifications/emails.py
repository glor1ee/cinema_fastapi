import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from exceptions import BaseEmailError

logger = logging.getLogger(__name__)


class EmailSender:
    def __init__(
        self,
        hostname: str,
        port: int,
        email: str,
        password: str,
        use_tls: bool,
        template_dir: str,
        activation_email_template_name: str,
        activation_complete_email_template_name: str,
        password_email_template_name: str,
        password_complete_email_template_name: str,
    ) -> None:
        self._hostname = hostname
        self._port = port
        self._email = email
        self._password = password
        self._use_tls = use_tls
        self._activation_template = activation_email_template_name
        self._activation_complete_template = activation_complete_email_template_name
        self._password_template = password_email_template_name
        self._password_complete_template = password_complete_email_template_name

        self._env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )

    async def _send_email(self, recipient: str, subject: str, html_content: str) -> None:
        message = MIMEMultipart()
        message["From"] = self._email
        message["To"] = recipient
        message["Subject"] = subject
        message.attach(MIMEText(html_content, "html"))

        try:
            smtp = aiosmtplib.SMTP(
                hostname=self._hostname, port=self._port, start_tls=self._use_tls
            )
            await smtp.connect()
            if self._use_tls:
                await smtp.starttls()
            if self._password:
                await smtp.login(self._email, self._password)
            await smtp.sendmail(self._email, [recipient], message.as_string())
            await smtp.quit()
        except aiosmtplib.SMTPException as error:
            logger.error("Failed to send email to %s: %s", recipient, error)
            raise BaseEmailError(f"Failed to send email to {recipient}: {error}") from error

    async def _render_and_send(
        self, template_name: str, subject: str, email: str, **context: str
    ) -> None:
        template = self._env.get_template(template_name)
        html_content = template.render(email=email, **context)
        await self._send_email(email, subject, html_content)

    async def send_activation_email(self, email: str, activation_link: str) -> None:
        await self._render_and_send(
            self._activation_template,
            "Activate your account",
            email,
            activation_link=activation_link,
        )

    async def send_activation_complete_email(self, email: str, login_link: str) -> None:
        await self._render_and_send(
            self._activation_complete_template,
            "Your account is active",
            email,
            login_link=login_link,
        )

    async def send_password_reset_email(self, email: str, reset_link: str) -> None:
        await self._render_and_send(
            self._password_template,
            "Reset your password",
            email,
            reset_link=reset_link,
        )

    async def send_password_reset_complete_email(self, email: str, login_link: str) -> None:
        await self._render_and_send(
            self._password_complete_template,
            "Your password has been changed",
            email,
            login_link=login_link,
        )
