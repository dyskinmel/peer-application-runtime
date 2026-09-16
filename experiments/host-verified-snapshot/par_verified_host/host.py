"""Opt-in verification reuse around unchanged private-host contracts.

Scope observations invalidate positive cryptographic results conservatively; they
never authorize an operation or suppress a filesystem/SQL/stream guard. Startup
uses the existing full-validation path with reuse explicitly disabled.
"""
from contextlib import contextmanager, ExitStack
import hashlib, os, threading

from par_keeper.contract import authority_body, dump
from par_upload_window import ReplaySpool
from par_window_host.host import owned
from par_crypto.errors import CryptoError
from .provider import VerificationProvider


def observe_host(provider, keeper, gateway):
    if type(provider) is not VerificationProvider:
        raise CryptoError('PROVIDER_REQUIRED')
    try:
        provider._guard()
        if (type(gateway) is not ReplaySpool or gateway.keeper is not keeper or
                keeper.provider is not provider or gateway.provider is not provider):
            raise CryptoError('PROVIDER_SCOPE')
        if keeper._closed or gateway.closed:
            raise CryptoError('CLOSED')
        if gateway.poison:
            raise CryptoError('RECOVERY_REQUIRED')
        # Not an integrity witness: these counters deliberately ONLY invalidate.
        # All actual state/authority/layout/content checks are still executed by
        # the unchanged Server, ReplaySpool and Keeper methods.
        db_authority=keeper.connection.execute('SELECT authority FROM metadata').fetchone()[0]
        data_version=keeper.connection.execute('PRAGMA data_version').fetchone()[0]
        scope=dump([authority_body(keeper.authority),db_authority,
                    keeper.connection.total_changes,data_version,
                    hashlib.sha256(gateway._last_raw or b'').digest(),gateway.phase,
                    hashlib.sha256(dump(gateway.config)).digest()])
        provider.observe_scope(scope)
    except BaseException:
        # Invalidating here must not hide the original failure or promote a result.
        if (os.getpid(),threading.get_ident()) == provider._owner and not provider._closed:
            provider._clear()
        raise


@contextmanager
def owned_verified(root, spool_root, cfg, base, secret, *, mode='full',
                   max_entries=512, max_key_bytes=4*1024*1024,
                   max_message_bytes=65536, allow_unpatched_sqlite=False):
    provider=VerificationProvider(base,mode=mode,max_entries=max_entries,
                                  max_key_bytes=max_key_bytes,max_message_bytes=max_message_bytes)
    try:
        with ExitStack() as stack:
            with provider.full_verification():
                keeper,gateway=stack.enter_context(owned(root,spool_root,cfg,provider,secret,
                                          allow_unpatched_sqlite=allow_unpatched_sqlite))
                # Opening retains the original full state and file validation.
                gateway._enter()
                observe_host(provider,keeper,gateway)
            startup=provider.statistics()
            yield keeper,gateway,provider,startup
    finally:
        provider.close()
