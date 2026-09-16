"""Private append-only intention journal, independent of the application ledger.

One cooperative PID/thread owns the flock. A pin is a lower bound, not an oracle
for an unseen tail or a rollback that also replaces the external pin. No GC.
"""
from __future__ import annotations
import copy,fcntl,hashlib,json,os,re,stat,threading
from pathlib import Path
from product.wp04.contracts import canonical
from product.wp04.inbox import private_dir,read_file
from par_store.fs import safe,sync_dir
from product.wp09.par_secure_fetch.persistence import require,FetchError
from .model import ApplicationIntent,JournalPin,PROFILE,MAX_BYTES,check_binding,check_receipt

MAX_EVENTS=256
MAX_INTENTS=64

def sha(raw):return hashlib.sha256(raw).hexdigest()

def decode_json(raw):
    try:
        value=json.loads(raw)
        require(canonical(value)==raw,'JOURNAL_CORRUPT')
        return value
    except Exception:raise FetchError('JOURNAL_CORRUPT')from None

class IntentJournal:
    @classmethod
    def create(cls,root,binding):
        binding=check_binding(binding);root=safe(Path(root));private_dir(root.parent)
        require(not root.exists(),'JOURNAL_EXISTS')
        # Fail closed on partial initialization; no automatic orphan deletion.
        root.mkdir(mode=0o700);private_dir(root)
        (root/'events').mkdir(mode=0o700)
        meta=canonical({'profile':PROFILE,'generation':os.urandom(16).hex(),'binding':binding.hex()})
        from product.wp09.par_secure_fetch.persistence import save_new
        save_new(root/'metadata.json',meta);sync_dir(root/'events');sync_dir(root);sync_dir(root.parent)
        pin=JournalPin(sha(meta),0,sha(meta))
        return cls.open(root,binding,expected_pin=pin)

    @classmethod
    def open(cls,root,binding,*,expected_pin):
        require(type(expected_pin)is JournalPin,'JOURNAL_PIN');binding=check_binding(binding)
        self=cls.__new__(cls);self.root=safe(Path(root));self._fd=None
        self._closed=False;self._poisoned=False;self._pid=os.getpid();self._thread=threading.get_ident()
        self.observer=None;self._pin=expected_pin;self._binding=binding
        self._anchor=None;self._anchor_pin=None
        try:
            private_dir(self.root);private_dir(self.root/'events')
            fd=os.open(self.root/'lease',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);self._fd=fd
            s=os.fstat(fd)
            require(stat.S_ISREG(s.st_mode)and s.st_nlink==1 and s.st_uid==os.getuid()and stat.S_IMODE(s.st_mode)==0o600,'UNSAFE_PATH')
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise FetchError('JOURNAL_LOCKED')from None
            self._root_signature=self._root_identity();self._reload(expected_pin,resync=True)
            return self
        except BaseException:
            if self._fd is not None:os.close(self._fd);self._fd=None
            self._closed=True;raise

    @classmethod
    def open_anchored(cls,root,binding,anchor):
        """Open against the externally kept prefix and fence any recovered tail.

        The caller owns the PinStore lifetime. This never enrolls a missing pin,
        and must finish its durable CAS before returning a mutation-capable handle.
        """
        from .anchors import PinStore
        require(isinstance(anchor,PinStore),'PIN_STORE_REQUIRED')
        binding=check_binding(binding);require(anchor.binding==binding,'PIN_STORE_BINDING')
        if hasattr(anchor,'root'):
            journal_path=Path(root).resolve();pin_path=Path(anchor.root).resolve()
            require(not pin_path.is_relative_to(journal_path)and not journal_path.is_relative_to(pin_path),'PIN_STORE_LOCATION')
        expected=anchor.load();require(type(expected)is JournalPin,'JOURNAL_PIN')
        journal=cls.open(root,binding,expected_pin=expected)
        journal._anchor=anchor;journal._anchor_pin=expected
        try:journal._sync_anchor();return journal
        except BaseException:journal._poisoned=True;journal.close();raise

    @property
    def anchored(self):
        self._guard();return self._anchor is not None

    def _sync_anchor(self):
        if self._anchor is not None:
            require(self._anchor.binding==self._binding,'PIN_STORE_BINDING')
            # Always load, even for an unchanged prefix. An unavailable, changed,
            # or rolled-back external pin must not be treated as a no-op success.
            require(self._anchor.load()==self._anchor_pin,'PIN_STORE_CONFLICT')
            if self._pin!=self._anchor_pin:
                self._anchor.advance(self._anchor_pin,self._pin)
                require(self._anchor.load()==self._pin,'PIN_STORE_CONFLICT')
                self._anchor_pin=self._pin

    def _root_identity(self):
        s=self.root.stat();e=(self.root/'events').stat();return (s.st_dev,s.st_ino,e.st_dev,e.st_ino)

    def _guard(self):
        require(os.getpid()==self._pid and threading.get_ident()==self._thread,'WRONG_OWNER')
        require(not self._closed,'JOURNAL_CLOSED');require(not self._poisoned,'JOURNAL_POISONED')
        private_dir(self.root);private_dir(self.root/'events')
        require(self._root_identity()==self._root_signature,'JOURNAL_REPLACED')

    def close(self):
        if self._closed:return
        require(os.getpid()==self._pid and threading.get_ident()==self._thread,'WRONG_OWNER')
        self._closed=True
        if self._fd is not None:
            os.close(self._fd);self._fd=None

    def _notify(self,stage):
        if self.observer:self.observer(stage)

    @staticmethod
    def _transition(state,payload,binding):
        require(type(payload)is dict and 'kind'in payload,'JOURNAL_CORRUPT')
        kind=payload['kind'];active=state['intent'];current=state['state']
        if kind=='PREPARE':
            require(set(payload)=={'kind','intent'},'JOURNAL_CORRUPT')
            try:intent=ApplicationIntent.from_bytes(bytes.fromhex(payload['intent']))
            except Exception:raise FetchError('JOURNAL_CORRUPT')from None
            require(intent.binding()==binding,'JOURNAL_BINDING')
            require(current in('EMPTY','RETIRED','ABANDONED'),'ACTIVE_INTENT')
            require(intent.operation_id.hex()not in state['used'],'OPERATION_RETIRED')
            require(len(state['used'])<MAX_INTENTS,'JOURNAL_BUDGET')
            state['used'][intent.operation_id.hex()]=intent.digest
            state.update(state='PREPARED',intent=intent,receipt=None)
            return
        require(active is not None and payload.get('intentDigest')==active.digest,'INTENT_PIN')
        if kind=='OBSERVE':
            require(set(payload)=={'kind','intentDigest','receipt'},'JOURNAL_CORRUPT')
            require(current in('DISPATCHED','OBSERVED'),'INQUIRY_REQUIRED')
            check_receipt(active,payload['receipt'])
            require(state['receipt']is None or canonical(state['receipt'])==canonical(payload['receipt']),'RECEIPT_CONFLICT')
            state.update(state='OBSERVED',receipt=copy.deepcopy(payload['receipt']));return
        require(set(payload)=={'kind','intentDigest'},'JOURNAL_CORRUPT')
        if kind=='DISPATCH':
            require(current=='PREPARED','INQUIRY_REQUIRED');state['state']='DISPATCHED'
        elif kind=='RETIRE':
            require(current=='OBSERVED','RECEIPT_REQUIRED');state['state']='RETIRED'
        elif kind=='ABANDON':
            require(current=='PREPARED','INQUIRY_REQUIRED');state['state']='ABANDONED'
        else:raise FetchError('JOURNAL_CORRUPT')

    def _reload(self,expected,resync=False):
        self._guard()
        require(set(p.name for p in self.root.iterdir())=={'metadata.json','events','lease'},'JOURNAL_CORRUPT')
        raw=read_file(self.root/'metadata.json',MAX_BYTES);meta=decode_json(raw);mh=sha(raw)
        require(mh==expected.metadata_digest,'JOURNAL_PIN')
        require(type(meta)is dict and set(meta)=={'profile','generation','binding'}and meta['profile']==PROFILE,'JOURNAL_CORRUPT')
        require(type(meta['generation'])is str and re.fullmatch('[0-9a-f]{32}',meta['generation'])is not None,'JOURNAL_CORRUPT')
        require(meta['binding']==self._binding.hex(),'JOURNAL_BINDING')
        names=sorted(p.name for p in(self.root/'events').iterdir())
        require(len(names)<=MAX_EVENTS,'JOURNAL_BUDGET')
        require(names==[f'{i:08d}.json'for i in range(1,len(names)+1)],'JOURNAL_CORRUPT')
        require(len(names)>=expected.sequence,'JOURNAL_PIN')
        state={'state':'EMPTY','intent':None,'receipt':None,'used':{}}
        previous=mh
        for sequence,name in enumerate(names,1):
            path=self.root/'events'/name;content=read_file(path,MAX_BYTES);event=decode_json(content)
            require(type(event)is dict and set(event)=={'profile','sequence','previous','payload'},'JOURNAL_CORRUPT')
            require(event['profile']==PROFILE and type(event['sequence'])is int and event['sequence']==sequence and event['previous']==previous,'JOURNAL_CORRUPT')
            self._transition(state,event['payload'],self._binding);previous=sha(content)
            if sequence==expected.sequence:require(previous==expected.event_digest,'JOURNAL_PIN')
            if resync:
                fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
                try:os.fsync(fd)
                finally:os.close(fd)
        if resync:sync_dir(self.root/'events');sync_dir(self.root)
        self._state=state;self._pin=JournalPin(mh,len(names),previous)

    def audit(self):
        try:self._reload(self._pin);self._sync_anchor()
        except BaseException:self._poisoned=True;raise

    def pin(self):
        self._guard();return self._pin

    @property
    def current(self):
        self.audit();return self._state['intent']

    def status(self):
        self.audit();s=self._state;i=s['intent']
        return {'state':s['state'],'intentDigest':None if i is None else i.digest,
                'operationId':None if i is None else i.operation_id.hex(),
                'receipt':copy.deepcopy(s['receipt']),
                'sequence':self._pin.sequence,'replayAllowed':False,
                'applied':False,'replicated':False,'acknowledged':False,'productQualified':False}

    def _append(self,payload):
        self.audit();require(self._pin.sequence<MAX_EVENTS,'JOURNAL_BUDGET')
        next_state=copy.deepcopy(self._state);self._transition(next_state,payload,self._binding)
        sequence=self._pin.sequence+1
        raw=canonical({'profile':PROFILE,'sequence':sequence,'previous':self._pin.event_digest,'payload':payload})
        require(0<len(raw)<=MAX_BYTES,'JOURNAL_BUDGET')
        path=self.root/'events'/f'{sequence:08d}.json'
        # Any failure after append entry is fail-closed. An incomplete file is
        # preserved for explicit diagnosis, never treated as a missing intent.
        try:
            self._notify('journal.before_create')
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb')as f:
                os.fchmod(f.fileno(),0o600);self._notify('journal.after_create')
                f.write(raw);f.flush();self._notify('journal.after_write')
                os.fsync(f.fileno());self._notify('journal.after_fsync')
            sync_dir(path.parent);self._notify('journal.after_dirsync')
            self._state=next_state;self._pin=JournalPin(self._pin.metadata_digest,sequence,sha(raw))
            self._sync_anchor()
            self._notify('journal.before_return')
        except BaseException as exc:
            self._poisoned=True
            if not isinstance(exc,Exception):raise
            raise FetchError('PERSISTENCE_UNKNOWN')from None
        return self.status()

    def prepare(self,intent):
        require(type(intent)is ApplicationIntent,'INTENT_INPUT');self.audit()
        require(intent.binding()==self._binding,'JOURNAL_BINDING')
        old=self._state['used'].get(intent.operation_id.hex())
        if old is not None:
            require(old==intent.digest,'OPERATION_ID_CONFLICT')
            require(self._state['intent']==intent and self._state['state']not in('RETIRED','ABANDONED'),'OPERATION_RETIRED')
            return self.status()
        return self._append({'kind':'PREPARE','intent':intent.to_bytes().hex()})

    def dispatch(self,digest):return self._append({'kind':'DISPATCH','intentDigest':digest})
    def observe(self,digest,receipt):
        self.audit();i=self._state['intent']
        require(i is not None and digest==i.digest,'INTENT_PIN');check_receipt(i,receipt)
        if self._state['state']=='OBSERVED':
            require(canonical(receipt)==canonical(self._state['receipt']),'RECEIPT_CONFLICT')
            return self.status()
        return self._append({'kind':'OBSERVE','intentDigest':digest,'receipt':copy.deepcopy(receipt)})
    def retire(self,digest):return self._append({'kind':'RETIRE','intentDigest':digest})
    def abandon(self,digest):return self._append({'kind':'ABANDON','intentDigest':digest})
