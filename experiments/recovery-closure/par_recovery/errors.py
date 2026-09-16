class RecoveryError(Exception):
    """Stable local error code. Payloads and keys are intentionally omitted."""
    def __init__(self,code):
        self.code=code
        super().__init__(code)
