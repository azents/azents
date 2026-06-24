"""Amazon SES email sending service."""

import dataclasses
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Annotated
from urllib.parse import urlparse

from fastapi import Depends
from jinja2 import Environment, PackageLoader
from types_aiobotocore_ses.client import SESClient

from azents.core.config import EmailConfig

from .deps import get_email_config, get_ses_client

logger = logging.getLogger(__name__)

# Verification code email subjects by language
VERIFICATION_CODE_SUBJECTS = {
    "ko": "[Azents] Verify your authentication code",
    "en": "[Azents] Your verification code",
}

# Invitation email subjects by language
INVITATION_SUBJECTS = {
    "ko": "[Azents] You have been invited to the {workspace_name} workspace",
    "en": "[Azents] You've been invited to {workspace_name}",
}

# Signup token email subjects by language
SIGNUP_TOKEN_SUBJECTS = {
    "ko": "[Azents] Complete your signup",
    "en": "[Azents] Complete your signup",
}

# Join request notification email subjects by language
JOIN_REQUEST_NOTIFICATION_SUBJECTS = {
    "ko": "[Azents] New join request for the {workspace_name} workspace",
    "en": "[Azents] New join request for {workspace_name}",
}

# Join request approval email subjects by language
JOIN_REQUEST_APPROVED_SUBJECTS = {
    "ko": "[Azents] Your request to join the {workspace_name} workspace was approved",
    "en": "[Azents] Your join request for {workspace_name} has been approved",
}

# Jinja2 template environment
_jinja_env = Environment(
    loader=PackageLoader("azents.core.email", "resources/templates"),
    autoescape=True,
)


@dataclasses.dataclass
class EmailService:
    """Email sending service using Amazon SES."""

    config: Annotated[EmailConfig | None, Depends(get_email_config)]
    ses_client: Annotated[SESClient | None, Depends(get_ses_client)]

    @property
    def configured(self) -> bool:
        """Check whether the email service is configured."""
        return self.config is not None and self.ses_client is not None

    async def send_verification_code(
        self,
        *,
        to_email: str,
        code: str,
        expire_minutes: int,
        language: str = "ko",
    ) -> None:
        """Send verification code email.

        When configured=False, only log and return.

        :param to_email: Recipient email
        :param code: 6-digit authentication code
        :param expire_minutes: Expiration time in minutes
        :param language: Language code (ko, en)
        """
        if not self.configured:
            logger.warning(
                "Email service not configured; skip sending verification code",
                extra={"to_email": to_email, "code": code},
            )
            return

        # Since configured=True, config and ses_client are not None
        assert self.config is not None
        assert self.ses_client is not None

        # fallback language
        lang = language if language in VERIFICATION_CODE_SUBJECTS else "en"

        # Extract domain for domain-bound code
        domain = ""
        if self.config.web_url:
            parsed = urlparse(self.config.web_url)
            domain = parsed.hostname or ""

        subject = VERIFICATION_CODE_SUBJECTS[lang]
        html_body = self._render_template(
            f"verification_code_{lang}.html",
            code=code,
            expire_minutes=expire_minutes,
            domain=domain,
        )
        text_body = self._render_template(
            f"verification_code_{lang}.txt",
            code=code,
            expire_minutes=expire_minutes,
            domain=domain,
        )

        await self._send_email(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )

    async def send_invitation(
        self,
        *,
        to_email: str,
        workspace_name: str,
        signup_url: str | None = None,
        language: str = "ko",
    ) -> None:
        """Send workspace invitation email.

        When configured=False, only log and return.

        :param to_email: Recipient email
        :param workspace_name: Workspace name
        :param signup_url: Signup URL for the new user
        :param language: Language code (ko, en)
        """
        if not self.configured:
            logger.warning(
                "Email service not configured; skip sending invitation email",
                extra={"to_email": to_email, "workspace_name": workspace_name},
            )
            return

        assert self.config is not None
        assert self.ses_client is not None

        lang = language if language in INVITATION_SUBJECTS else "en"
        login_path = "/login?next=/workspaces"
        if self.config.web_url:
            login_url = f"{self.config.web_url}{login_path}"
        else:
            login_url = login_path

        subject = INVITATION_SUBJECTS[lang].format(workspace_name=workspace_name)
        html_body = self._render_template(
            f"invitation_{lang}.html",
            workspace_name=workspace_name,
            login_url=login_url,
            signup_url=signup_url,
        )
        text_body = self._render_template(
            f"invitation_{lang}.txt",
            workspace_name=workspace_name,
            login_url=login_url,
            signup_url=signup_url,
        )

        await self._send_email(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )

    async def send_signup_token(
        self,
        *,
        to_email: str,
        signup_url: str,
        expire_hours: int,
        language: str = "ko",
    ) -> bool:
        """Send signup token email.

        When configured=False, do not send and return False.

        :param to_email: Recipient email
        :param signup_url: Signup link
        :param expire_hours: Expiration time
        :param language: Language code
        :return: True when sent
        """
        if not self.configured:
            logger.warning(
                "Email service not configured, skipping signup token email",
                extra={"to_email": to_email},
            )
            return False

        assert self.config is not None
        assert self.ses_client is not None

        lang = language if language in SIGNUP_TOKEN_SUBJECTS else "en"
        subject = SIGNUP_TOKEN_SUBJECTS[lang]
        html_body = self._render_template(
            f"signup_token_{lang}.html",
            signup_url=signup_url,
            expire_hours=expire_hours,
        )
        text_body = self._render_template(
            f"signup_token_{lang}.txt",
            signup_url=signup_url,
            expire_hours=expire_hours,
        )

        await self._send_email(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )
        return True

    async def send_join_request_notification(
        self,
        *,
        workspace_name: str,
        workspace_handle: str,
        language: str = "ko",
    ) -> None:
        """Send join request notification email to managers/owners.

        Currently only logs without directly querying manager email list.
        Actual recipient list will be implemented later.

        :param workspace_name: Workspace name
        :param workspace_handle: Workspace handle
        :param language: Language code (ko, en)
        """
        if not self.configured:
            logger.warning(
                "Email service not configured, skipping join request notification",
                extra={
                    "workspace_name": workspace_name,
                    "workspace_handle": workspace_handle,
                },
            )
            return

        assert self.config is not None
        assert self.ses_client is not None

        lang = language if language in JOIN_REQUEST_NOTIFICATION_SUBJECTS else "en"

        manage_path = f"/w/{workspace_handle}/settings/members"
        if self.config.web_url:
            manage_url = f"{self.config.web_url}{manage_path}"
        else:
            manage_url = manage_path

        logger.info(
            "Join request notification ready",
            extra={
                "workspace_name": workspace_name,
                "manage_url": manage_url,
                "language": lang,
            },
        )

    async def send_join_request_approved(
        self,
        *,
        user_id: str,
        workspace_name: str,
        language: str = "ko",
    ) -> None:
        """Send join request approval email.

        :param user_id: Approved user ID
        :param workspace_name: Workspace name
        :param language: Language code (ko, en)
        """
        if not self.configured:
            logger.warning(
                "Email service not configured, skipping join request approved email",
                extra={
                    "user_id": user_id,
                    "workspace_name": workspace_name,
                },
            )
            return

        lang = language if language in JOIN_REQUEST_APPROVED_SUBJECTS else "en"
        logger.info(
            "Join request approved notification ready",
            extra={
                "user_id": user_id,
                "workspace_name": workspace_name,
                "language": lang,
            },
        )

    def _render_template(self, template_name: str, **kwargs: object) -> str:
        """Render Jinja2 template."""
        template = _jinja_env.get_template(template_name)
        return template.render(**kwargs)

    async def _send_email(
        self,
        *,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
    ) -> None:
        """Send email.

        :param to_email: Recipient email
        :param subject: Subject
        :param html_body: HTML body
        :param text_body: Text body
        """
        assert self.config is not None
        assert self.ses_client is not None

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{self.config.sender_name} <{self.config.sender}>"
        msg["To"] = to_email

        text_part = MIMEText(text_body, "plain", "utf-8")
        msg.attach(text_part)

        html_part = MIMEText(html_body, "html", "utf-8")
        msg.attach(html_part)

        response = await self.ses_client.send_raw_email(
            Source=self.config.sender,
            Destinations=[to_email],
            RawMessage={"Data": msg.as_string()},
        )
        message_id = response.get("MessageId")
        logger.info(
            "Email sent successfully",
            extra={"to_email": to_email, "message_id": message_id},
        )
