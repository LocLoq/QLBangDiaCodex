from __future__ import annotations

import hashlib
import json
import smtplib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import numpy as np


@dataclass(frozen=True)
class MediaPayload:
    tmdb_id: int
    title: str
    overview: str
    poster_path: str | None
    vote_average: float | None
    release_date: str | None
    raw: dict[str, Any]


class TmdbClient:
    base_url = "https://api.themoviedb.org/3"

    def __init__(self, api_key: str, timeout: float = 20.0) -> None:
        self.api_key = api_key
        self.client = httpx.Client(timeout=timeout, headers={"accept": "application/json"})

    def _get(self, path: str, **params) -> dict[str, Any]:
        params["api_key"] = self.api_key
        for attempt in range(4):
            response = self.client.get(f"{self.base_url}{path}", params=params)
            if response.status_code != 429 and response.status_code < 500:
                response.raise_for_status()
                return response.json()
            if attempt == 3:
                response.raise_for_status()
            retry_after = response.headers.get("retry-after")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 0.5 * (2 ** attempt)
            time.sleep(delay)
        raise RuntimeError("TMDB retry loop kết thúc bất thường.")

    def discover_movies(self, page: int, language: str = "vi-VN") -> list[MediaPayload]:
        data = self._get("/discover/movie", page=page, language=language, include_adult="false", sort_by="popularity.desc")
        return [self._movie_payload(row) for row in data.get("results", [])]

    def discover_shows(self, page: int, language: str = "vi-VN") -> list[MediaPayload]:
        data = self._get("/discover/tv", page=page, language=language, include_adult="false", sort_by="popularity.desc")
        return [self._show_payload(row) for row in data.get("results", [])]

    def movie_detail(self, tmdb_id: int, language: str = "vi-VN") -> dict[str, Any]:
        return self._get(f"/movie/{tmdb_id}", language=language, append_to_response="credits,reviews,keywords,release_dates")

    def show_detail(self, tmdb_id: int, language: str = "vi-VN") -> dict[str, Any]:
        return self._get(f"/tv/{tmdb_id}", language=language, append_to_response="aggregate_credits,reviews,keywords,content_ratings")

    def season_detail(self, show_id: int, season_number: int, language: str = "vi-VN") -> dict[str, Any]:
        return self._get(f"/tv/{show_id}/season/{season_number}", language=language)

    @staticmethod
    def _localized(preferred: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        """Keep Vietnamese values when present and fill only missing fields from English."""
        localized = dict(fallback)
        localized.update({key: value for key, value in preferred.items() if value not in (None, "", [], {})})
        return localized

    def localized_show_detail(self, tmdb_id: int) -> dict[str, Any]:
        preferred = self.show_detail(tmdb_id, "vi-VN")
        fallback = self.show_detail(tmdb_id, "en-US")
        return self._localized(preferred, fallback)

    def localized_movie_detail(self, tmdb_id: int) -> dict[str, Any]:
        preferred = self.movie_detail(tmdb_id, "vi-VN")
        fallback = self.movie_detail(tmdb_id, "en-US")
        return self._localized(preferred, fallback)

    def localized_season_detail(self, show_id: int, season_number: int) -> dict[str, Any]:
        preferred = self.season_detail(show_id, season_number, "vi-VN")
        fallback = self.season_detail(show_id, season_number, "en-US")
        return self._localized(preferred, fallback)

    @staticmethod
    def _movie_payload(row: dict[str, Any]) -> MediaPayload:
        return MediaPayload(row["id"], row.get("title", "Không rõ tên"), row.get("overview", ""), row.get("poster_path"), row.get("vote_average"), row.get("release_date"), row)

    @staticmethod
    def _show_payload(row: dict[str, Any]) -> MediaPayload:
        return MediaPayload(row["id"], row.get("name", "Không rõ tên"), row.get("overview", ""), row.get("poster_path"), row.get("vote_average"), row.get("first_air_date"), row)

    def close(self) -> None:
        self.client.close()


class PosterCache:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)

    def path_for(self, poster_path: str) -> Path:
        digest = hashlib.sha256(poster_path.encode()).hexdigest()
        return self.folder / f"{digest}.jpg"

    def fetch(self, poster_path: str) -> Path:
        target = self.path_for(poster_path)
        if target.exists():
            return target
        response = httpx.get(f"https://image.tmdb.org/t/p/w342{poster_path}", timeout=20)
        response.raise_for_status()
        target.write_bytes(response.content)
        return target


class GeminiSearch:
    """Optional semantic search. All methods safely fall back when no key is configured."""
    def __init__(
        self,
        api_key: str | None,
        embedding_model: str = "gemini-embedding-001",
        embedding_dimensions: int = 768,
    ) -> None:
        self.api_key = api_key
        self.embedding_model = embedding_model
        self.embedding_dimensions = embedding_dimensions
        self.last_error: str | None = None
        self._client = None

    def _get_client(self):
        if not self.api_key:
            self.last_error = "missing_key"
            return None
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def embed(self, text: str) -> np.ndarray | None:
        try:
            client = self._get_client()
            if client is None:
                return None
            response = client.models.embed_content(
                model=self.embedding_model,
                contents=text,
                config={"output_dimensionality": self.embedding_dimensions},
            )
            return np.asarray(response.embeddings[0].values, dtype=np.float32)
        except Exception as exc:
            self.last_error = str(exc)
            return None

    def rerank(self, model: str, profile: str, candidates: list[dict], limit: int) -> list[dict] | None:
        """Return only validated JSON-friendly recommendations, never customer PII.

        Validation of ids against the candidate set intentionally remains in the
        application layer, where a malformed model response can be repaired with
        the local ranking fallback.
        """
        try:
            client = self._get_client()
            if client is None:
                return None
            prompt = (
                "Chon toi da " + str(limit) + " phim tu danh sach ung vien de goi y. "
                "Khong de xuat phim ngoai danh sach. Tra ve JSON object co khoa 'items'; "
                "moi item gom item_id (so nguyen) va reason (mot cau tieng Viet ngan).\n"
                f"Ho so an danh: {profile}\nUng vien: {candidates}"
            )
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            payload = json.loads(response.text or "{}")
            items = payload.get("items", []) if isinstance(payload, dict) else []
            return items if isinstance(items, list) else None
        except Exception as exc:
            self.last_error = str(exc)
            return None

    def unavailable_reason(self) -> str:
        error = (self.last_error or "").lower()
        if any(marker in error for marker in ("429", "resource_exhausted", "quota", "rate limit")):
            return "Gemini has reached its request or quota limit; retry after it resets."
        if self.last_error == "missing_key":
            return "Gemini API key is missing."
        return "Embedding could not be created; check the Gemini connection or service status."

    @staticmethod
    def cosine(query: np.ndarray, documents: np.ndarray) -> np.ndarray:
        denominator = np.linalg.norm(documents, axis=1) * np.linalg.norm(query)
        return np.divide(documents @ query, denominator, out=np.zeros_like(denominator), where=denominator != 0)


class SmtpSender:
    def __init__(self, host: str, port: int, username: str, password: str, starttls: bool = True) -> None:
        self.host, self.port, self.username, self.password, self.starttls = host, port, username, password, starttls

    def send(self, sender: str, recipient: str, subject: str, body: str) -> None:
        message = f"From: {sender}\r\nTo: {recipient}\r\nSubject: {subject}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{body}"
        with smtplib.SMTP(self.host, self.port, timeout=20) as smtp:
            if self.starttls:
                smtp.starttls()
            smtp.login(self.username, self.password)
            smtp.sendmail(sender, [recipient], message.encode("utf-8"))


class MockSmsSender:
    def send(self, phone: str, body: str) -> dict[str, str]:
        return {"provider": "mock", "status": "MOCK_SENT", "phone": phone, "body": body}
