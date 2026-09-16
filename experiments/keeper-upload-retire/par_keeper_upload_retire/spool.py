"""Explicit staging-only reclamation for a cooperative POSIX owner.

The original upload metadata is preserved and bound to a Keeper-signed journal.
INTENT and PAYLOAD_REMOVED still consume the declared reservation. Only a synced
TOMBSTONED journal releases it. Record slots are never recycled. Keeper DB and
objects are not mutated. Reopen audits but never completes a pending deletion.
"""
from pathlib import Path
import os
import re
import threading

from par_store.fs import WriterLock, safe, sync_dir
from par_recovery.transfer import read_file, mkdir
from par_keeper.contract import authority_body, dump as keeper_dump
from par_keeper_upload.spool import Spool, MAX_BYTES, MAX_RECORDS, META_LIMIT, private, sha
from par_keeper_upload import protocol as upload
from . import contract as c
E = c.E
PHASES = ('INTENT', 'PAYLOAD_REMOVED', 'TOMBSTONED')


class RetiringSpool(Spool):
    """A schema2 candidate: old Spool must not open this directory.

    Methods retire/rebind are trusted-host API only, not added IPC methods.
    No automatic expiry, recursive removal, or deletion of Keeper data.
    """
    def __init__(self, keeper, root, *, max_bytes=MAX_BYTES, max_records=MAX_RECORDS,
                 allow_migrate=False, observer=None):
        self.keeper = keeper; self.provider = keeper.provider
        self.root = safe(Path(root)); self.observer = observer
        self.closed = True; self.poison = False; self.lock = None
        self.busy = False; self.thread = threading.get_ident()
        c.integer(max_bytes, 1, MAX_BYTES); c.integer(max_records, 1, MAX_RECORDS)
        if type(allow_migrate) is not bool:
            raise E('STAGING_SETTINGS')
        if keeper._thread != self.thread or keeper._closed:
            raise E('OWNER_REQUIRED')
        self.limits = {0: 2, 1: keeper.public, 2: max_bytes, 3: max_records}
        try:
            mkdir(self.root); private(self.root, True); self.lock = WriterLock(self.root)
            cfg = self.root / 'LIMITS.cbor'
            if cfg.exists():
                private(cfg)
                previous = upload.load(read_file(cfg, 4096), 4096)
                if previous != self.limits:
                    old = dict(self.limits); old[0] = 1
                    if previous != old:
                        raise E('STAGING_SETTINGS')
                    if not allow_migrate:
                        raise E('STAGING_MIGRATION_REQUIRED')
                    if list(self.root.glob('*.retirement')):
                        raise E('STAGING_CORRUPT')
                    # Validate old data before the one-file schema marker switch.
                    self.closed = False; self._recover()
                    self._atomic(cfg, self.limits, 'retirement.migrate')
            else:
                if any(p.name != '.store.lock' for p in self.root.iterdir()):
                    raise E('STAGING_CORRUPT')
                self._atomic(cfg, self.limits, 'retirement.init')
            self.closed = False; self._recover()
        except BaseException:
            self.close(); raise

    def _journal_path(self, token):
        return self._path(token, '.retirement')

    def _original(self, token):
        """Validate the original metadata without assuming payload still exists."""
        path = self._path(token, '.cbor')
        if not path.exists():
            raise E('STAGE_UNKNOWN')
        private(path); raw = read_file(path, META_LIMIT)
        m = upload.load(raw, META_LIMIT); upload.keys(m, range(8))
        upload.integer(m[0], 1, 1); upload.fixed(m[1]); upload.fixed(m[4])
        b = upload.check_command(self.provider, m[2])
        if b[2] != 'begin' or upload.token_for(self.provider, m[2]) != token or m[1] != token:
            raise E('STAGING_CORRUPT')
        upload.integer(m[3], 0, b[7][2])
        if m[5] not in ('active', 'committed'):
            raise E('STAGING_CORRUPT')
        if m[5] == 'active' and (m[6] is not None or m[7] is not None):
            raise E('STAGING_CORRUPT')
        return raw, m, b

    def _identity(self, token):
        path = self._path(token, '.part'); private(path)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            before = os.fstat(fd)
            if before.st_size > max(upload.MAX_INDEX, upload.MAX_OBJECT):
                raise E('STAGING_CORRUPT')
            with os.fdopen(fd, 'rb', closefd=False) as f:
                raw = f.read(before.st_size + 1)
            after = os.fstat(fd)
            identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
            if identity(before) != identity(after) or len(raw) != before.st_size:
                raise E('STAGING_CORRUPT')
            return [before.st_dev, before.st_ino, before.st_size, sha(raw)]
        finally:
            os.close(fd)

    def _receipt_body(self, journal):
        return {0: 1, 1: c.PROFILE, 2: self.keeper.public, 3: journal[3],
                 4: c.digest(journal[5][-1]), 5: journal[8], 6: journal[7][2],
                 7: 'TOMBSTONED', 8: False, 9: False, 10: False}

    def _receipt(self, journal):
        return c.signed(self.provider, self.keeper._seed, 'receipt', self._receipt_body(journal))

    def _validate_journal(self, token, *, payload=True):
        original, m, b = self._original(token)
        path = self._journal_path(token); private(path)
        raw = read_file(path, c.MAX_BYTES)
        j = c.verified(self.provider, raw, 'journal', self.keeper.public)
        c.keys(j, range(10)); c.version(j)
        if (j[2], j[3], j[4]) != (self.keeper.public, token, c.digest(original)) or m[5] != 'active':
            raise E('RETIREMENT_JOURNAL')
        if type(j[5]) is not list or not 1 <= len(j[5]) <= c.MAX_REBINDS or j[6] not in PHASES:
            raise E('RETIREMENT_JOURNAL')
        seen = set(); previous = None
        for req in j[5]:
            _, _, grant = c.check_request(self.provider, req, m[2], self.keeper.public)
            rid = c.request_id(self.provider, req)
            if rid in seen or (previous is not None and grant[2][3] <= previous[3]):
                raise E('RETIREMENT_JOURNAL')
            if previous is not None:
                c._authority_order(previous, grant[2])
            previous = grant[2]; seen.add(rid)
        ident = j[7]
        if type(ident) is not list or len(ident) != 4:
            raise E('RETIREMENT_JOURNAL')
        for v in ident[:3]: c.integer(v, 0, 2**64-1)
        c.fixed(ident[3]); c.integer(j[8], 1, max(upload.MAX_INDEX, upload.MAX_OBJECT))
        if ident[2:] != [m[3], m[4]] or j[8] != b[7][2]:
            raise E('RETIREMENT_JOURNAL')
        if j[6] == 'TOMBSTONED':
            receipt = c.verified(self.provider, j[9], 'receipt', self.keeper.public)
            # Exact equality also rejects bool-as-int through canonical bytes.
            if c.dump(receipt) != c.dump(self._receipt_body(j)):
                raise E('RETIREMENT_JOURNAL')
        elif j[9] is not None:
            raise E('RETIREMENT_JOURNAL')
        part = self._path(token, '.part')
        if payload and part.exists():
            if j[6] != 'INTENT':
                raise E('RETIREMENT_DATA_REAPPEARED')
            if self._identity(token) != ident:
                raise E('RETIREMENT_PAYLOAD_CHANGED')
        return j, m, b

    def _save_journal(self, j, label):
        raw = c.signed(self.provider, self.keeper._seed, 'journal', j)
        # _atomic takes a decoded object and applies canonical encoding once.
        self._atomic(self._journal_path(j[3]), c.load(raw), label)

    def _records(self):
        records = []
        for path in self.root.glob('*.cbor'):
            if path.name == 'LIMITS.cbor': continue
            if not re.fullmatch('[0-9a-f]{64}', path.stem):
                raise E('STAGING_CORRUPT')
            token = bytes.fromhex(path.stem)
            if self._journal_path(token).exists():
                j, m, b = self._validate_journal(token)
                m = dict(m)
                if j[6] == 'TOMBSTONED': m[5] = 'retired'
                records.append((m, b))
            else:
                records.append(super()._meta(token))
        return records

    def _recover(self):
        tokens = set(); parts = []; journals = set(); temps = []
        for path in list(self.root.iterdir()):
            private(path)
            if path.name in ('LIMITS.cbor', '.store.lock'): continue
            if re.fullmatch('[0-9a-f]{64}\\.cbor', path.name): tokens.add(bytes.fromhex(path.stem))
            elif re.fullmatch('[0-9a-f]{64}\\.part', path.name): parts.append(path)
            elif re.fullmatch('[0-9a-f]{64}\\.retirement', path.name): journals.add(bytes.fromhex(path.stem))
            elif re.fullmatch(r'\.upload-[a-zA-Z0-9_-]+\.tmp', path.name): temps.append(path)
            else: raise E('STAGING_CORRUPT')
        if not journals <= tokens or len(tokens) > self.limits[3]:
            raise E('STAGING_CORRUPT')
        all_ids = set()
        for token in tokens:
            if token in journals:
                j, _, _ = self._validate_journal(token)
                for req in j[5]:
                    rid = c.request_id(self.provider, req)
                    if rid in all_ids: raise E('RETIREMENT_OPERATION_DUPLICATE')
                    all_ids.add(rid)
            else:
                m, _ = super()._meta(token, True)
                if m[5] == 'committed': self._retire(token)
        # As in schema1, only never-acknowledged files and atomic temp files.
        for path in parts:
            if bytes.fromhex(path.stem) not in tokens: path.unlink()
        for path in temps: path.unlink()
        sync_dir(self.root)
        if sum(b[7][2] for m, b in self._records() if m[5] == 'active') > self.limits[2]:
            raise E('STAGING_CORRUPT')

    def _guard_upload(self, raw):
        command = upload.check_command(self.provider, raw)
        if command[2] == 'seal': return
        token = (upload.token_for(self.provider, raw) if command[2] == 'begin'
                 else command[7][0] if command[2] in ('chunk', 'reserve') else command[7])
        if self._journal_path(token).exists():
            j, _, _ = self._validate_journal(token)
            raise E('STAGE_RETIRED' if j[6] == 'TOMBSTONED' else 'RETIREMENT_PENDING')

    def execute(self, raw):
        self._enter(); self._guard_upload(raw)
        return super().execute(raw)

    def stamp(self, raw):
        self._enter(); self._guard_upload(raw)
        return super().stamp(raw)

    def _authorize(self, raw, begin):
        k = self.keeper
        with k._operation():
            if k.connection.execute('SELECT authority FROM metadata').fetchone()[0] != keeper_dump(authority_body(k.authority)):
                raise E('STALE_AUTHORITY')
            return c.check_request(self.provider, raw, begin, k.public, k.authority)

    def _unique(self, raw, token):
        rid = c.request_id(self.provider, raw)
        for path in self.root.glob('*.retirement'):
            other = bytes.fromhex(path.stem)
            j, _, _ = self._validate_journal(other)
            for existing in j[5]:
                if c.request_id(self.provider, existing) == rid and (existing != raw or other != token):
                    raise E('OPERATION_CONFLICT')

    def _locate(self, raw):
        _, _, grant = c.inspect_request(self.provider, raw)
        token = grant[5]; original, m, b = self._original(token)
        self._authorize(raw, m[2])
        if m[5] == 'committed': raise E('STAGE_COMMITTED')
        self._unique(raw, token)
        return token, original, m, b

    def retire(self, raw):
        self._enter(); self.busy = True
        try:
            token, original, m, b = self._locate(raw)
            path = self._journal_path(token)
            if path.exists():
                j, m, b = self._validate_journal(token)
                if j[5][-1] != raw:
                    if j[6] == 'TOMBSTONED': raise E('RETIREMENT_CONFLICT')
                    raise E('RETIREMENT_REBIND_REQUIRED')
                if j[6] == 'TOMBSTONED': return self._result(j)
            else:
                super()._meta(token)  # Verify acknowledged payload before fixing intent.
                ident = self._identity(token)
                if ident[2:] != [m[3], m[4]]: raise E('RECOVERY_REQUIRED')
                j = {0: 1, 1: c.PROFILE, 2: self.keeper.public, 3: token,
                     4: c.digest(original), 5: [raw], 6: 'INTENT', 7: ident,
                     8: b[7][2], 9: None}
                self._authorize(raw, m[2]); self._save_journal(j, 'retirement.intent')
            if j[6] == 'INTENT':
                self._emit('retirement.before_unlink')
                self._authorize(raw, m[2])
                j, m, b = self._validate_journal(token)
                part = self._path(token, '.part')
                if part.exists(): part.unlink()
                self._emit('retirement.after_unlink'); sync_dir(self.root)
                self._emit('retirement.after_sync'); self._authorize(raw, m[2])
                j[6] = 'PAYLOAD_REMOVED'; self._save_journal(j, 'retirement.removed')
            self._emit('retirement.before_credit')
            self._authorize(raw, m[2]); j, _, _ = self._validate_journal(token)
            # Resync even on a restart where the unlink had already happened.
            sync_dir(self.root)
            j[6] = 'TOMBSTONED'; j[9] = self._receipt(j)
            self._save_journal(j, 'retirement.tombstone'); self._emit('retirement.ack')
            return self._result(j)
        except OSError:
            self.poison = True; raise E('OUTCOME_UNKNOWN') from None
        finally:
            self.busy = False

    def rebind(self, raw):
        """Replace only the authorization for an existing immutable intent."""
        self._enter(); self.busy = True
        try:
            token, original, m, b = self._locate(raw)
            if not self._journal_path(token).exists(): raise E('RETIREMENT_NOT_PENDING')
            j, _, _ = self._validate_journal(token)
            if j[6] == 'TOMBSTONED': raise E('STAGE_RETIRED')
            if j[5][-1] == raw: return self._status(j)
            if len(j[5]) >= c.MAX_REBINDS: raise E('RETIREMENT_REBIND_LIMIT')
            old = c.inspect_request(self.provider, j[5][-1])[2][2]
            new = c.inspect_request(self.provider, raw)[2][2]
            if new[3] <= old[3]: raise E('RETIREMENT_REBIND_ORDER')
            c._authority_order(old, new)
            j[5].append(raw); self._authorize(raw, m[2])
            self._save_journal(j, 'retirement.rebind'); return self._status(j)
        except OSError:
            self.poison = True; raise E('OUTCOME_UNKNOWN') from None
        finally:
            self.busy = False

    @staticmethod
    def _status(j):
        return {'stage': j[3], 'state': j[6], 'authorization_records': len(j[5]),
                'reservation_released_bytes': j[8] if j[6] == 'TOMBSTONED' else 0,
                'record_reclaimed': False, 'keeper_mutated': False, 'product_qualified': False}

    def _result(self, j):
        result = self._status(j)
        result.update(unlinked_payload_bytes=j[7][2], receipt=j[9])
        return result

    def retirement_status(self, token):
        self._enter(); c.fixed(token)
        if not self._journal_path(token).exists(): raise E('RETIREMENT_NOT_PENDING')
        j, _, _ = self._validate_journal(token)
        return self._status(j)

    def diagnostics(self):
        result = super().diagnostics()
        states = [self._validate_journal(bytes.fromhex(p.stem))[0][6]
                  for p in self.root.glob('*.retirement')]
        result.update(retired_records=states.count('TOMBSTONED'),
                      retirement_pending=sum(s != 'TOMBSTONED' for s in states),
                      record_quota_reclaimed=False, automatic_gc=False)
        return result
