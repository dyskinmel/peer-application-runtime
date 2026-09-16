"""Owner-local positive Ed25519 verification snapshots, NOT authorization caching.

All caller-side parsing, revocation, generation, disk and response guards still run.
Only exact immutable (key, message, signature) successes may be reused. No digest-
only keys, timestamps, failures, secrets, decryption results or persistent cache.
"""
from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
import json
import os
import threading
import time

from par_crypto.provider import SodiumProvider, fixed, bounded, MAX_INPUT
from par_crypto.errors import CryptoError


class VerificationProvider:
    """Opt-in, bounded optimization around one already-pinned native provider.

    key_bytes counts retained byte strings, not Python heap/RSS. Entry count bounds
    container overhead separately. Full verification is the default. This wrapper
    is intentionally neither transferable nor a security boundary against same-
    process code rewriting provider internals.
    """

    def __init__(self, base, *, mode='full', max_entries=512,
                 max_key_bytes=4*1024*1024, max_message_bytes=65536):
        if type(base) is not SodiumProvider:
            raise CryptoError('PROVIDER_REQUIRED')
        if type(mode) is not str or mode not in ('full', 'signatures'):
            raise CryptoError('CACHE_CONFIG')
        for value, low, high in ((max_entries,1,4096),
                                  (max_key_bytes,1,64*1024*1024),
                                  (max_message_bytes,0,MAX_INPUT)):
            if type(value) is not int or not low <= value <= high:
                raise CryptoError('CACHE_CONFIG')
        self._base = base
        self._instance = base
        self._verifier = base.verify
        self._identity_raw = self._identity_bytes()
        self._owner = (os.getpid(), threading.get_ident())
        self._mode = mode
        self._limits = (max_entries, max_key_bytes, max_message_bytes)
        self._cache = OrderedDict()
        self._key_bytes = 0
        self._scope = None
        self._closed = False
        self._poisoned = False
        self._full_depth = 0
        self._epoch = 0
        self._counts = {k: 0 for k in ('attempts','backend_calls','hits','bypasses',
                                      'failures','evictions','invalidations',
                                      'backend_nanoseconds','peak_entries','peak_key_bytes')}

    def _identity_bytes(self):
        try:
            return json.dumps(self._base.identity, sort_keys=True,
                              separators=(',', ':'), allow_nan=False).encode('utf-8')
        except Exception:
            raise CryptoError('PROVIDER_CHANGED') from None

    def _check_owner(self):
        if (os.getpid(), threading.get_ident()) != self._owner:
            raise CryptoError('OWNER_REQUIRED')

    def _clear(self):
        self._cache.clear()
        self._key_bytes = 0
        self._epoch += 1
        self._counts['invalidations'] += 1

    def _guard(self):
        self._check_owner()
        if self._closed:
            raise CryptoError('CLOSED')
        if self._poisoned:
            raise CryptoError('PROVIDER_CHANGED')
        try:
            changed = (self._base is not self._instance or
                       self._base.verify != self._verifier or
                       self._identity_bytes() != self._identity_raw)
        except Exception:
            changed = True
        if changed:
            self._clear()
            self._poisoned = True
            raise CryptoError('PROVIDER_CHANGED')

    @property
    def identity(self):
        self._guard()
        return json.loads(self._identity_raw)

    def statistics(self):
        self._check_owner()
        return {**self._counts, 'mode':self._mode, 'epoch':self._epoch,
                'entries':len(self._cache), 'key_bytes':self._key_bytes,
                'max_entries':self._limits[0], 'max_key_bytes':self._limits[1],
                'max_message_bytes':self._limits[2], 'closed':self._closed,
                'poisoned':self._poisoned, 'authorization_cached':False,
                'disk_reads_skipped':False, 'persistent_cache':False,
                'product_qualified':False}

    def invalidate(self, reason='operator'):
        self._guard()
        if type(reason) is not str or not 1 <= len(reason) <= 80:
            raise CryptoError('INVALID_INPUT')
        # Reasons are not retained: callers could accidentally pass sensitive data.
        self._clear()

    def observe_scope(self, value):
        """Conservative invalidation hint; NEVER evidence to skip a live read."""
        self._guard()
        bounded(value,4096)
        if value != self._scope:
            self._clear()
            self._scope = value

    @contextmanager
    def full_verification(self):
        """Cold full-check epoch, used at startup and explicit full audits."""
        self._guard()
        self._clear()
        self._full_depth += 1
        try:
            yield self
        finally:
            self._full_depth -= 1
            self._clear()

    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> None:
        self._guard()
        self._counts['attempts'] += 1
        try:
            fixed(public_key,32)
            fixed(signature,64)
            bounded(message)
        except Exception:
            self._counts['failures'] += 1
            self._clear()
            raise
        # Exact bytes, not hashes. Python hashes only index this dict; equality
        # still compares every component. Equal digest/mtime cannot yield a hit.
        key = (public_key, message, signature)
        size = 96 + len(message)
        eligible = (self._mode == 'signatures' and self._full_depth == 0 and
                    len(message) <= self._limits[2] and size <= self._limits[1])
        if eligible and key in self._cache:
            self._cache.move_to_end(key)
            self._counts['hits'] += 1
            return None
        if not eligible:
            self._counts['bypasses'] += 1
        self._counts['backend_calls'] += 1
        started = time.perf_counter_ns()
        try:
            result = self._base.verify(public_key,message,signature)
            if result is not None:
                raise CryptoError('BACKEND_CONTRACT')
            self._guard()
        except BaseException:
            self._counts['failures'] += 1
            self._clear()
            raise
        finally:
            self._counts['backend_nanoseconds'] += time.perf_counter_ns()-started
        if eligible:
            while self._cache and (len(self._cache) >= self._limits[0] or
                                   self._key_bytes + size > self._limits[1]):
                _, old_size = self._cache.popitem(last=False)
                self._key_bytes -= old_size
                self._counts['evictions'] += 1
            self._cache[key] = size
            self._key_bytes += size
            self._counts['peak_entries'] = max(self._counts['peak_entries'],len(self._cache))
            self._counts['peak_key_bytes'] = max(self._counts['peak_key_bytes'],self._key_bytes)
        return None

    def _call(self, method, *args):
        self._guard()
        try:
            return getattr(self._base,method)(*args)
        except BaseException:
            self._clear()
            raise

    # Explicit forwarding only; never cache secret-dependent operations/results.
    def sign_public(self, seed):return self._call('sign_public',seed)
    def sign(self, seed, message):return self._call('sign',seed,message)
    def dh_public(self, secret):return self._call('dh_public',secret)
    def dh(self, secret, public_key):return self._call('dh',secret,public_key)
    def seal(self,key,nonce,aad,plaintext):return self._call('seal',key,nonce,aad,plaintext)
    def open(self,key,nonce,aad,ciphertext):return self._call('open',key,nonce,aad,ciphertext)
    def seal_ietf(self,key,nonce,aad,plaintext):return self._call('seal_ietf',key,nonce,aad,plaintext)
    def open_ietf(self,key,nonce,aad,ciphertext):return self._call('open_ietf',key,nonce,aad,ciphertext)

    def close(self):
        self._check_owner()
        if not self._closed:
            self._clear()
            self._scope = None
            self._closed = True

    def __reduce_ex__(self, protocol):
        raise TypeError('VerificationProvider is process-local and cannot be serialized')
