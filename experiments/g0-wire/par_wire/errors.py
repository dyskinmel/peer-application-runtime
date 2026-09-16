"""Stable, data-free local errors. No peer payload is interpolated into messages."""
class WireError(ValueError):
    def __init__(self, code: str, path: str = ''):
        self.code = code
        self.path = path
        super().__init__(code + (': ' + path if path else ''))
