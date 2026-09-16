"""Immutable in-memory read-only recovery view, no writer/nonce/local-cache import.

Existing file inspection/export routines are reused after signature and exact
attachment validation. Every open from disk must re-run recipient verification.
"""
from __future__ import annotations
from pathlib import Path
from par_file import inspect_file,export_file
from .errors import RecoveryError as E
class _Blocks:
    def __init__(self,public,root):
        self.root=Path(root) if root is not None else Path('/__par_no_source_store__')
        self.raw={}
        import hashlib
        for e in public.body[14]:
            for oid in e[4]:
                raw=public.data[oid];self.raw[hashlib.sha256(raw).digest()]=raw
    def read_block(self,locator):
        if locator not in self.raw:raise E('OBJECT_REFERENCE')
        return self.raw[locator]
class RecoveryView:
    def __init__(self,public,pin,provider,secret,*,storage_root=None):
        self._provider=provider;self._storage=_Blocks(public,storage_root)
        self._secret=secret;self._bindings=public.bindings;self._payloads=dict(public.plaintexts)
        self._pin=pin;self._seeds=dict(public.state._active.seeds)
    def _enter(self,write=False):
        if write:raise E('READ_ONLY')
    def attachments(self,eid):
        if eid not in self._bindings:raise E('OBJECT_REFERENCE')
        return self._bindings[eid]
    def read_change(self,eid):
        if eid not in self._payloads:raise E('OBJECT_REFERENCE')
        return self._payloads[eid]
    def read_seed(self,object_id):
        if object_id not in self._seeds:raise E('OBJECT_REFERENCE')
        return self._seeds[object_id]
    def file_info(self,eid):return inspect_file(self,eid,self._secret)
    def export_file(self,eid,destination,*,observer=None):return export_file(self,eid,self._secret,destination,observer=observer)
    def status(self):
        return {'state':'RECIPIENT_VALIDATED_READ_ONLY','objects_complete':True,'signed_history_verified':True,
                'recipient_authorized':True,'payloads_decrypted':True,'whole_files_verified':sum(bool(x) for x in self._bindings.values()),
                'envelopes':len(self._payloads),'roots':[x.hex() for x in self._pin.roots],
                'seed_semantics':'OPAQUE_BYTES','inner_validated':False,'applied':False,'writable':False,
                'global_latest_proven':False,'network_verified':False,'product_qualified':False}
