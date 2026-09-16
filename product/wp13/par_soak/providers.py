"""Reusable disposable-namespace contracts; never a security attestation.

Factories are explicitly injected, not located by provider name. A missing
provider is BLOCKED; no memory/filesystem fallback is constructed here.
"""
from __future__ import annotations
from dataclasses import replace
from .campaign import need

def pin_conformance(create,reopen,initial,advanced):
    if create is None or reopen is None:return {'result':'BLOCKED','reason':'PIN_PROVIDER_NOT_SUPPLIED','checks':[],'os_protection_proven':False}
    from product.wp09.par_application_intent import JournalPin,PinStore
    from product.wp09.par_secure_fetch.persistence import FetchError
    need(callable(create)and callable(reopen),'CONFORMANCE_FACTORY')
    need(type(initial)is JournalPin and type(advanced)is JournalPin and initial.metadata_digest==advanced.metadata_digest and advanced.sequence>initial.sequence,'CONFORMANCE_INPUT')
    checks=[];p=None
    def rejected(fn,code):
        try:fn()
        except FetchError as exc:
            need(exc.code==code,'CONFORMANCE_ERROR_CLASS');return
        raise ValueError('CONFORMANCE_REJECTION_MISSING')
    try:
        p=create();need(isinstance(p,PinStore)and callable(getattr(p,'close',None)),'CONFORMANCE_PROVIDER')
        need(p.load()==initial,'CONFORMANCE_INITIAL_READBACK');checks.append('initial')
        p.advance(initial,advanced);need(p.load()==advanced,'CONFORMANCE_ADVANCE_READBACK');checks.append('advance')
        p.close();p=None;p=reopen();need(p.load()==advanced,'CONFORMANCE_REOPEN_READBACK');checks.append('reopen')
        rejected(lambda:p.advance(initial,advanced),'PIN_STORE_CONFLICT');checks.append('compare_swap')
        rejected(lambda:p.advance(advanced,initial),'PIN_STORE_REGRESSION');checks.append('monotonic_sequence')
        rejected(lambda:p.advance(advanced,replace(advanced,event_digest='0'*64 if advanced.event_digest!='0'*64 else'1'*64)),'PIN_STORE_CONFLICT');checks.append('same_sequence_identity')
        p.advance(advanced,advanced);need(p.load()==advanced,'CONFORMANCE_NOOP_READBACK');checks.append('idempotent')
        return {'result':'PASS','checks':checks,'os_protection_proven':False,'scope':'DISPOSABLE_PROVIDER_CONTRACT_ONLY'}
    finally:
        if p is not None:p.close()
