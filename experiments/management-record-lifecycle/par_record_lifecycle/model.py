"""Event-replayed, pure lifecycle model. No files are removed, no grants are issued.

Inputs represent already-verified generation-bound requests. Cryptographic
request verification, durable admission fencing and archive resolvers in the
real gateways are *assumptions to be implemented*, not provided by this model.
"""
from __future__ import annotations
import copy
from . import contracts as c

MAX_EVENTS = 256
MAX_GENERATIONS = 64
MAX_ARCHIVE_ESTIMATE = 64 * 1024 * 1024

class LifecycleModel:
    def __init__(self, inventory):
        self.initial = c.decode_inventory(c.encode_inventory(inventory))
        c.require(self.initial['source']=='MODEL_FIXTURE', 'MODEL_ONLY')
        self._inventory = copy.deepcopy(self.initial)
        self._events = []
        self.generation = 1
        self.closed_through = 0
        self.phase = 'OPEN'
        self._archives = []
        self._pending = None

    def _all_records(self):
        out = [r for a in self._archives for r in a['records']]
        active = self._inventory['records']
        # Between ARCHIVED and COMPACTED, records have both logical locations.
        keys = {r['key'] for r in out}
        out += [r for r in active if r['key'] not in keys]
        return sorted(out, key=lambda r:r['key'])

    def _scope(self):
        v = copy.deepcopy(self._inventory)
        active = {r['key'] for r in v['records']}
        anchors = {a['key']:a for a in v['anchors']}
        for r in self._all_records():
            if r['key'] not in active:
                anchors[r['key']] = {'key':r['key'], 'proof_digest':r['proof_digest']}
        v['anchors'] = sorted(anchors.values(), key=lambda a:a['key'])
        return v

    def plan(self):
        occupied=sum(r['storage_bytes'] for a in self._archives for r in a['records'])
        remaining=max(0,MAX_ARCHIVE_ESTIMATE-occupied)
        p = c.plan(self._scope(),archive_limit=remaining)
        p.update(generation=self.generation, phase=self.phase,
                 history_digest=self._prefix(len(self._events)))
        return p

    def _run(self, event):
        c.require(len(self._events) < MAX_EVENTS, 'CAPACITY')
        trial = copy.deepcopy(self)
        event = c.decode(c.canonical(event))
        trial._apply(event)
        trial._events.append(event)
        trial.checkpoint()  # Enforce the complete bounded checkpoint size.
        self.__dict__.update(trial.__dict__)
        return self.view()

    def close(self, expected_plan, *, controller_revision):
        return self._run({'action':'close', 'plan':expected_plan, 'controller_revision':controller_revision})

    def archive(self):
        return self._run({'action':'archive'})

    def compact(self):
        return self._run({'action':'compact'})

    def open_next(self, *, controller_revision):
        return self._run({'action':'open', 'controller_revision':controller_revision})

    def rotate(self, public, revision):
        return self._run({'action':'rotate', 'public':public, 'controller_revision':revision})

    def admit(self, record, *, generation, controller_revision):
        return self._run({'action':'admit', 'record':record, 'generation':generation,
                          'controller_revision':controller_revision})

    def _controller(self, revision):
        c.integer(revision, 1)
        c.require(self._inventory['controller'] is not None and revision==self._inventory['controller_revision'], 'STALE_CONTROLLER')

    def _apply(self, e):
        c.require(type(e) is dict and type(e.get('action')) is str)
        action = e['action']
        if action=='admit':
            c.keys(e, ('action','record','generation','controller_revision'))
            c.integer(e['generation'],1,MAX_GENERATIONS); self._controller(e['controller_revision'])
            c.require(e['generation']>self.closed_through, 'GENERATION_CLOSED')
            c.require(self.phase=='OPEN', 'PHASE')
            c.require(e['generation']==self.generation, 'GENERATION')
            r = c.validate_record(e['record'])
            previous = self._all_records()
            if r['kind']=='submission' and r['evidence_digest'] is not None:
                target=next(ref for ref in r['refs'] if ref.startswith('job:'))
                match=next((row for row in previous if row['key']==target), None)
                c.require(match is not None and match['intent_digest']==r['evidence_digest'],'REFERENCE_MISMATCH')
            c.require(r['key'] not in {x['key'] for x in previous}, 'ID_REUSE')
            if r['kind']=='job':
                c.require(not any(x['kind']=='job' and x['intent_digest']==r['intent_digest'] for x in previous), 'INTENT_ALIAS')
            self._inventory['records'].append(copy.deepcopy(r))
            self._inventory['records'].sort(key=lambda x:x['key'])
            c.validate_inventory(self._scope())
        elif action=='close':
            c.keys(e, ('action','plan','controller_revision')); self._controller(e['controller_revision'])
            c.require(self.phase=='OPEN', 'PHASE')
            p = self.plan()
            c.require(c.canonical(e['plan'])==c.canonical(p), 'STALE_PLAN')
            c.require(p['model_ready'], 'BLOCKED')
            self._pending = {'generation':self.generation, 'records':copy.deepcopy(self._inventory['records']),
                             'inventory_digest':p['inventory_digest'], 'approval_revision':e['controller_revision']}
            # In a durable implementation this fence must be fsynced before removal.
            self.closed_through = self.generation
            self.phase = 'CLOSED'
        elif action=='archive':
            c.keys(e, ('action',)); c.require(self.phase=='CLOSED', 'PHASE')
            archive = copy.deepcopy(self._pending)
            c.require(archive['records']==self._inventory['records'], 'ARCHIVE_MISMATCH')
            archive['digest'] = c.sha(c.canonical(archive))
            self._archives.append(archive)
            self.phase = 'ARCHIVED'
        elif action=='compact':
            c.keys(e, ('action',)); c.require(self.phase=='ARCHIVED', 'PHASE')
            archive = copy.deepcopy(self._archives[-1]); digest = archive.pop('digest')
            c.require(c.sha(c.canonical(archive))==digest and archive==self._pending, 'ARCHIVE_MISMATCH')
            c.require(archive['records']==self._inventory['records'], 'ARCHIVE_MISMATCH')
            self._inventory['records'] = []  # Pure in-memory location change ONLY.
            self.phase = 'COMPACTED'
        elif action=='open':
            c.keys(e, ('action','controller_revision')); self._controller(e['controller_revision'])
            c.require(self.phase=='COMPACTED', 'PHASE')
            c.require(self.generation<MAX_GENERATIONS, 'CAPACITY')
            self.generation += 1; self.phase='OPEN'; self._pending=None
        elif action=='rotate':
            c.keys(e, ('action','public','controller_revision')); c.hex32(e['public']); c.integer(e['controller_revision'],1)
            c.require(self.phase=='OPEN', 'PHASE')
            c.require(e['controller_revision']>self._inventory['controller_revision'], 'STALE_CONTROLLER')
            self._inventory['controller']=e['public']; self._inventory['controller_revision']=e['controller_revision']
        else:
            raise c.LifecycleError('SCHEMA')

    def resolve(self, key):
        c.ref_key(key)
        for r in self._all_records():
            if r['key']==key:
                return copy.deepcopy(r)
        raise c.LifecycleError('NOT_FOUND')

    def view(self):
        return {'scope':'PURE_NON_DESTRUCTIVE_MODEL', 'generation':self.generation,
                'closed_through':self.closed_through, 'phase':self.phase,
                'active_records':len(self._inventory['records']),
                'archived_records':sum(len(a['records']) for a in self._archives),
                'controller_revision':self._inventory['controller_revision'],
                'sequence':len(self._events), 'simulation':True,
                'real_deletion_allowed':False, 'product_qualified':False}

    def _prefix(self, n):
        return c.sha(c.canonical({'initial':self.initial,'events':self._events[:n]}))

    def checkpoint(self):
        return c.canonical({'schema':1,'profile':c.PROFILE,'scope':'PURE_NON_DESTRUCTIVE_MODEL',
                            'initial':self.initial,'events':self._events})

    def pin(self):
        return {'schema':1,'profile':c.PROFILE,'keeper':self.initial['keeper'],'store':self.initial['store'],
                'sequence':len(self._events),'prefix_digest':self._prefix(len(self._events)),
                'generation':self.generation,'closed_through':self.closed_through,
                'controller_revision':self._inventory['controller_revision']}

    @classmethod
    def restore(cls, raw, *, expected_pin):
        c.require(expected_pin is not None,'PIN_REQUIRED')
        p=expected_pin
        c.keys(p,('schema','profile','keeper','store','sequence','prefix_digest','generation','closed_through','controller_revision'))
        c.integer(p['schema'],1,1); c.require(p['profile']==c.PROFILE)
        for k in ('keeper','store','prefix_digest'):c.hex32(p[k])
        c.integer(p['sequence'],0,MAX_EVENTS);c.integer(p['generation'],1,MAX_GENERATIONS)
        c.integer(p['closed_through'],0,MAX_GENERATIONS);c.integer(p['controller_revision'],1)
        d=c.decode(raw);c.keys(d,('schema','profile','scope','initial','events'))
        c.integer(d['schema'],1,1);c.require(d['profile']==c.PROFILE and d['scope']=='PURE_NON_DESTRUCTIVE_MODEL')
        c.require(type(d['events']) is list and len(d['events'])<=MAX_EVENTS)
        c.require(p['sequence']<=len(d['events']),'PIN_MISMATCH')
        model=cls(d['initial'])
        if p['sequence']==0:c.require(model.pin()==p,'PIN_MISMATCH')
        for n,event in enumerate(d['events'],1):
            model._run(event)
            if n==p['sequence']:c.require(model.pin()==p,'PIN_MISMATCH')
        return model
