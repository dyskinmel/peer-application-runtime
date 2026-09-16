class AuthError(Exception):
    """Stable reason code; deliberately excludes secrets and input bytes."""
    def __init__(self,code):self.code=code;super().__init__(code)
