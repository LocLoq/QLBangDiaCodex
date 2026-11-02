from contextlib import contextmanager

import numpy as np
import pytest

from normastore.application.embeddings import build_embeddings


def test_provider_failure_keeps_completed_batches_only(monkeypatch):
    saved = []

    class Repository:
        def __init__(self, session):
            pass

        def candidates(self, limit):
            return [
                (number, f"Movie {number}", "Overview", None, None, None) for number in range(26)
            ]

        def save_batch(self, rows, model):
            saved.append((list(rows), model))

    class Provider:
        calls = 0

        def embed(self, text):
            self.calls += 1
            return np.ones(2, dtype="float32") if self.calls <= 25 else None

        def unavailable_reason(self):
            return "provider unavailable"

    @contextmanager
    def uow():
        yield type("Unit", (), {"session": object()})()

    monkeypatch.setattr("normastore.application.embeddings.EmbeddingRepository", Repository)
    with pytest.raises(RuntimeError, match="provider unavailable"):
        build_embeddings(uow, Provider(), "model", 2)
    assert len(saved) == 1
    assert len(saved[0][0]) == 25
