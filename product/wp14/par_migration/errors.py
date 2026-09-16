from __future__ import annotations


class MigrationError(RuntimeError):
    """Stable fail-closed error for the local migration candidate."""

    def __init__(self, code: str, *, detail: str | None = None):
        self.code = code
        self.detail = detail
        super().__init__(code if detail is None else f"{code}:{detail}")
