from __future__ import annotations

import os
from pathlib import Path

import keyring

from normastore.config import Settings
from normastore.infrastructure.external import GeminiSearch, MockSmsSender, PosterCache, SmtpSender
from normastore.infrastructure.pdf_receipts import PdfReceiptExporter


class Integrations:
    """Application adapters for local credentials and external providers."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.gemini_factory = GeminiSearch
        self.poster_cache = PosterCache(settings.cache_dir / "posters")

    def gemini_api_key(self) -> str | None:
        return (
            os.environ.get("NORMASTORE_GEMINI_API_KEY")
            or self.settings.gemini_api_key
            or keyring.get_password("normastore", "gemini")
        )

    def gemini_key_source(self) -> str:
        if os.environ.get("NORMASTORE_GEMINI_API_KEY"):
            return "biến môi trường"
        if keyring.get_password("normastore", "gemini"):
            return "Windows Credential Manager"
        return "chưa cấu hình"

    def save_gemini_key(self, value: str) -> None:
        keyring.set_password("normastore", "gemini", value.strip())

    def delete_gemini_key(self) -> None:
        try:
            keyring.delete_password("normastore", "gemini")
        except keyring.errors.PasswordDeleteError:
            pass

    def email_sender(self):
        settings = self.settings
        if not (settings.smtp_host and settings.smtp_username and settings.smtp_from):
            return None
        password = keyring.get_password("normastore", "smtp")
        if not password:
            return None
        smtp = SmtpSender(
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_username,
            password,
            settings.smtp_starttls,
        )
        return lambda recipient, body: smtp.send(
            settings.smtp_from, recipient, "Nhắc hạn trả đĩa NormaStore", body
        )

    def send_sms(self, recipient: str, body: str) -> None:
        MockSmsSender().send(recipient, body)

    def send_test_email(self) -> None:
        settings = self.settings
        password = keyring.get_password("normastore", "smtp")
        if not (settings.smtp_host and settings.smtp_username and settings.smtp_from and password):
            raise ValueError(
                "Cần host, username, email gửi và App Password trong Windows Credential Manager."
            )
        SmtpSender(
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_username,
            password,
            settings.smtp_starttls,
        ).send(
            settings.smtp_from,
            settings.smtp_from,
            "NormaStore SMTP test",
            "SMTP NormaStore đã cấu hình thành công.",
        )

    def export_receipt(self, receipt, path: Path, layout: str) -> None:
        PdfReceiptExporter().export(receipt, path, layout)
