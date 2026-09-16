"""Redacted error surface. Payload bytes and raw SQL exceptions never enter messages."""
from __future__ import annotations

class StoreError(Exception):
    def __init__(self, code: str, *, operation_id: bytes | None = None, sqlite_code: int | None = None):
        self.code = code
        self.operation_id = operation_id
        self.sqlite_code = sqlite_code
        super().__init__(code)
