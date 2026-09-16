class ServiceError(Exception):
    """Stable local service code; never include user payload or private key data."""
    def __init__(self,code):
        self.code=code
        super().__init__(code)
