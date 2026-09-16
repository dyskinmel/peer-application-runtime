"""Explicit semantic-core -> existing authenticated local Store candidate.

This is an owner-process boundary, not a sandbox. The default refuses synthetic
core reports; test mode is for public synthetic fixtures ONLY and never reports
innerValidated. No durable CRDT application is claimed, even with a real core.
"""
from __future__ import annotations
import hashlib, hmac, os, threading
from dataclasses import dataclass, field
from .contracts import ChangeInput, CheckedReport, SharedChangeError, require, core_request, check_report, canonical
from .dependencies import collect_dependencies,stamp

@dataclass(frozen=True)
class PreparedSharedChange:
    request_hash: str
    report: CheckedReport = field(repr=False)
    bound: object = field(repr=False)
    _owner: object = field(repr=False, compare=False)
    _seal: bytes = field(repr=False, compare=False)

class SharedWriter:
    def __init__(self,writer,core,*,app_id,space_id,document_id,schema_id,allow_contract_double=False):
        require(type(app_id) is str and type(allow_contract_double) is bool)
        for x in (space_id,document_id,schema_id):require(type(x) is bytes and len(x)==32)
        self._writer=writer;self._core=core;self._scope=(app_id,space_id,document_id);self._schema=schema_id
        self._allow=allow_contract_double;self._pid=os.getpid();self._thread=threading.get_ident()
        self._closed=False;self._busy=False;self._seal=os.urandom(32)
    def _enter(self):
        require(os.getpid()==self._pid and threading.get_ident()==self._thread,'WRONG_OWNER')
        require(not self._closed,'CLOSED');require(not self._busy,'REENTRANT_OPERATION')
        self._writer.store._enter()
    def close(self):self._enter();self._closed=True;self._seal=b''
    def _tag(self,request_hash,report,bound):
        return hmac.digest(self._seal,canonical([request_hash,report.engine,report.note,report.semantic_validated,bound.prepared.fingerprint.hex()]),'sha256')
    def _check(self,op,header,payload):
        require(type(op) is bytes and len(op)==16)
        change=ChangeInput.create(header,payload,schema_id=self._schema);h=change.header
        require((h[0],h[1],h[3])==self._scope,'SCOPE_MISMATCH')
        # No dependency work or nonce allocation when the declared backend is absent/test-only.
        try:identity=dict(self._core.identity)
        except Exception:raise SharedChangeError('CORE_UNAVAILABLE') from None
        require(identity.get('kind')=='automerge' or (self._allow and identity.get('kind')=='contract-test-double'),'CORE_NOT_REAL')
        owner=self._writer.store;before=stamp(owner,h[1])
        deps=collect_dependencies(owner,change,self._writer.crypto.epoch_secret,schema_id=self._schema)
        request=core_request(change,deps)
        try:raw=self._core.validate(request)
        except SharedChangeError:raise
        except Exception:raise SharedChangeError('CORE_FAILURE') from None
        require(identity==self._core.identity,'CORE_IDENTITY_CHANGED')
        checked=check_report(request,raw,expected_engine=identity,allow_contract_double=self._allow)
        require(before==stamp(owner,h[1]),'OWNER_STATE_CHANGED')
        # The cache is an encrypted candidate preview, not an applied/materialized DB view.
        cache=canonical({'profile':'par-shared-preview-local-0032','core':checked.engine,
                         'innerValidated':checked.semantic_validated,'applied':False,'note':checked.note})
        return change,checked,cache
    def prepare(self,op,header,payload):
        self._enter();self._busy=True
        try:
            change,report,cache=self._check(op,header,payload)
            bound=self._writer.prepare(op,change.header,change.payload,cache)
            return PreparedSharedChange(report.request_hash,report,bound,self,self._tag(report.request_hash,report,bound))
        finally:self._busy=False
    def _result(self,receipt,report):
        return {'operationId':receipt.operation_id.hex(),'commitId':receipt.envelope_id.hex(),
                'storeGeneration':receipt.store_generation.hex(),'localCommitted':True,
                'innerValidated':report.semantic_validated,'applied':False,'replicated':False,
                'evidenceKind':'PINNED_CORE_LOCAL_CANDIDATE' if report.semantic_validated else 'CONTRACT_TEST_DOUBLE_REAL_STORE'}
    def commit(self,prepared):
        self._enter()
        require(type(prepared) is PreparedSharedChange and prepared._owner is self,'FOREIGN_PREPARED_CHANGE')
        require(hmac.compare_digest(prepared._seal,self._tag(prepared.request_hash,prepared.report,prepared.bound)),'PREPARED_CHANGED')
        require(prepared.report.engine==self._core.identity,'CORE_IDENTITY_CHANGED')
        self._busy=True
        try:
            # Existing Store validates authority and fence again inside its commit transaction.
            receipt=self._writer.store.commit(prepared.bound)
            return self._result(receipt,prepared.report)
        finally:self._busy=False
    def write(self,op,header,payload):
        self._enter();self._busy=True
        try:
            change,report,cache=self._check(op,header,payload)
            old=self._writer.read_committed(op,change.header,change.payload,cache)
            if old is not None:return self._result(old,report)
            bound=self._writer.prepare(op,change.header,change.payload,cache)
            require(report.engine==self._core.identity,'CORE_IDENTITY_CHANGED')
            receipt=self._writer.store.commit(bound)
            return self._result(receipt,report)
        finally:self._busy=False
