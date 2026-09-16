"""Synchronous local adapter into the existing recovery Inbox. Never opens a socket."""
import secrets
from .contract import make_call
class AuthorizedProvider:
    def __init__(self,keeper,lease,capability,provider,subject_seed):
        self.keeper=keeper;self.lease=lease;self.capability=capability;self.provider=provider;self._subject_seed=subject_seed
    def fetch(self,oid):
        call=make_call(self.provider,self._subject_seed,self.capability,'get',self.lease,secrets.token_bytes(32),oid)
        return self.keeper.fetch(self.lease,oid,self.capability,call)
