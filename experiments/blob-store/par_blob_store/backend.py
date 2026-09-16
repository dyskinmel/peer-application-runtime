from par_auth_store.backend import BoundStorage
from . import schema
class BlobStorage(BoundStorage):
    USER_VERSION=3
    @classmethod
    def schema_sql(cls):return schema.sql()
    @classmethod
    def schema_profile(cls):return schema.digest()
    @classmethod
    def schema_matches(cls,c):return schema.matches(c)
