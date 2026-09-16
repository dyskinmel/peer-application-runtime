"""Matrix cells reuse the existing append-only campaign storage mechanics.

A new manifest profile and explicit per-cell child-exit vectors avoid borrowing
0054's two-process SEAL for a different process topology. One cell is the atomic
resume boundary; a crashed cell is ambiguous, never automatically repeated.
"""
from __future__ import annotations
from pathlib import Path
from product.wp13.par_soak.campaign import Campaign,need,pack,sha,config_value

class MatrixCampaign(Campaign):
    @staticmethod
    def manifest(binding,config):
        need(type(config)is dict and set(config)=={'cells','seed'},'MATRIX_CONFIG')
        cells=config['cells'];need(type(cells)is list and 1<=len(cells)<=8,'MATRIX_CONFIG')
        config_value(binding,{'rounds':len(cells),'seed':config['seed']})
        for c in cells:
            need(type(c)is dict and set(c)=={'participants','max_active','rounds_per_peer'},'MATRIX_CONFIG')
            need(type(c['participants'])is int and c['participants']in(2,8),'MATRIX_CONFIG')
            need(type(c['max_active'])is int and 1<=c['max_active']<=c['participants'],'MATRIX_CONFIG')
            need(type(c['rounds_per_peer'])is int and 1<=c['rounds_per_peer']<=4,'MATRIX_CONFIG')
        import json
        return json.loads(pack({'profile':'par-resource-matrix-0055','binding':binding,
                         'config':{'rounds':len(cells),'seed':config['seed'],'cells':cells}}))
    @classmethod
    def create(cls,root,binding,config):
        manifest=cls.manifest(binding,config);root=Path(root);root.mkdir(mode=0o700);obj=cls._lock(root)
        try:
            obj._write('manifest.json',manifest);obj._manifest=manifest;obj._events=[];obj._reopened=False;return obj
        except BaseException:obj.close();raise
    @classmethod
    def open(cls,root,binding,config,*,pin=None):
        expected=cls.manifest(binding,config);obj=cls._lock(Path(root))
        try:
            obj._manifest=obj._read('manifest.json');need(obj._manifest==expected,'MATRIX_BINDING')
            names=set(p.name for p in obj.root.iterdir());need(names>={'lease','manifest.json'},'CAMPAIGN_CORRUPT')
            events=sorted(names-{'lease','manifest.json'});need(len(events)<=40,'CAMPAIGN_BUDGET')
            need(events==[f'{i:06}.json'for i in range(1,len(events)+1)],'CAMPAIGN_CORRUPT');obj._events=[]
            for name in events:
                value=obj._read(name);need(type(value)is dict and set(value)=={'sequence','previous','kind','payload'},'CAMPAIGN_CORRUPT')
                need(type(value['sequence'])is int and value['sequence']==len(obj._events)+1 and value['previous']==obj.pin()['digest'],'CAMPAIGN_CORRUPT')
                obj._validate(value['kind'],value['payload'],replaying=True);obj._events.append(value)
            if pin is not None:
                need(type(pin)is dict and set(pin)=={'sequence','digest'}and type(pin['sequence'])is int,'CAMPAIGN_PIN')
                n=pin['sequence'];need(0<=n<=len(obj._events),'CAMPAIGN_PIN')
                need(pin['digest']==sha(obj._manifest if n==0 else obj._events[n-1]),'CAMPAIGN_PIN')
            obj._sync();obj._reopened=True;return obj
        except BaseException:obj.close();raise
    def scenario(self,index):
        need(type(index)is int and 0<=index<len(self._manifest['config']['cells']),'ROUND_ORDER')
        c=self._manifest['config']['cells'][index];return f"peers{c['participants']}-active{c['max_active']}-rounds{c['rounds_per_peer']}"
    def _unsealed_results(self):
        rows=[]
        for e in self._events:
            if e['kind']=='SEAL':rows=[]
            elif e['kind']=='RESULT':rows.append(e['payload'])
        return rows
    def _validate(self,kind,payload,*,replaying=False):
        def valid(value,code):need(value,'CAMPAIGN_CORRUPT'if replaying else code)
        if kind=='SEAL':
            s=self._status();valid(s['first_failure']is None,'CAMPAIGN_FAILED')
            rows=self._unsealed_results()
            valid(type(payload)is dict and set(payload)=={'through','child_exit_codes'}and type(payload['through'])is int,'CAMPAIGN_FINALIZATION')
            codes=payload['child_exit_codes']
            valid(type(codes)is list and all(type(v)is list and all(type(x)is int and x==0 for x in v)for v in codes),'CAMPAIGN_FINALIZATION')
            expected=[r['child_exit_codes']for r in rows]
            valid(bool(rows)and s['active']is None and payload['through']==s['completed']and payload['child_exit_codes']==expected,'CAMPAIGN_FINALIZATION')
            valid(all(all(type(x)is int and x==0 for x in v)for v in expected),'CAMPAIGN_FINALIZATION');return
        super()._validate(kind,payload,replaying=replaying)
        if kind=='RESULT':
            c=self._manifest['config']['cells'][payload['round']]
            valid(all(type(payload.get(k))is int and payload[k]==v for k,v in c.items()),'MATRIX_CELL')
            if payload['status']=='PASS':
                codes=payload.get('child_exit_codes')
                valid(type(codes)is list and len(codes)==c['participants']and all(type(x)is int and x==0 for x in codes),'CAMPAIGN_FINALIZATION')
                valid(payload.get('readonly_unchanged')is True and payload.get('violations')==[],'MATRIX_READONLY')
    def seal(self,child_exit_codes):
        self._append('SEAL',{'through':self._status()['completed'],'child_exit_codes':child_exit_codes})
