"""Public errors deliberately omit raw native errors, keys, and payloads."""
class CryptoError(Exception):
    def __init__(self, code: str):
        self.code=code
        super().__init__(code)
