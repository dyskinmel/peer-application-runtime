"""Same-DB adapter for the existing transactional payload Store.

Its raw commit/configure methods are not supported public write paths. Private
Python access and the SQLite connection are not an OS security boundary.
"""
from par_store.store import Store
from . import schema
from .errors import AuthorityStoreError as E

class BoundStorage(Store):
    USER_VERSION=2
    @classmethod
    def schema_sql(cls):return schema.sql()
    @classmethod
    def schema_profile(cls):return schema.digest()
    @classmethod
    def schema_matches(cls,c):return schema.matches(c)
    def commit(self,p,*,fencing_token):
        owner=getattr(self,'authority',None)
        if owner is None or owner._pending is None:raise E('AUTHORIZATION_REQUIRED')
        return super().commit(p,fencing_token=fencing_token)
    def configure_space(self,*args,**kwargs):raise E('AUTHORIZATION_REQUIRED')
    def advance_epoch(self,*args,**kwargs):raise E('AUTHORIZATION_REQUIRED')
    def _authorize_commit(self,p,token):
        if not self.connection.in_transaction:raise E('AUTHORIZATION_REQUIRED')
        self.authority._guard(self.authority._pending,p,token)
    def _commit_authority_meta(self,p):self.authority._record_commit(p)
    def _envelope_state(self,p):return 'pending'
    def audit(self):
        owner=getattr(self,'authority',None)
        return owner.audit() if owner is not None else super().audit()
