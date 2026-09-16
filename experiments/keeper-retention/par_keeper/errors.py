class KeeperError(Exception):
    """Stable local candidate error, without payload or key material in messages."""
    def __init__(self,code):self.code=code;super().__init__(code)
