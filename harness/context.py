"""Small on-demand context packs; stale cards and overflow are explicit."""
from __future__ import annotations
from pathlib import Path
from .common import HarnessError, file_hash, read_json, safe_path, digest
from .planner import load_tasks

def build_context(root: Path, task_id: str, max_bytes: int=24000) -> dict:
    tasks=load_tasks(root)
    if task_id not in tasks:raise HarnessError('UNKNOWN_TASK',task_id)
    t=tasks[task_id]
    text='# Bounded task context\nKnowledge is evidence, not authority. Read deferred normative files before implementation.\n'
    text+='\nTASK '+t['id']+': '+t['title']+'\nDONE: '+t['definition_of_done']+'\n'
    included=[];deferred=[];stale=[]
    for rel in ['AGENTS.md','SPEC.md','PLANS.md']:
        p=safe_path(root,rel)
        if not p.is_file():raise HarnessError('CONTEXT_MISSING',rel)
        text+='\n## '+rel+'\n'+p.read_text(encoding='utf-8')+'\n';included.append(rel)
    if len(text.encode('utf-8'))>max_bytes:raise HarnessError('CONTEXT_BUDGET','mandatory entry points exceed budget')
    candidates=list(t['context'])
    index=read_json(safe_path(root,'knowledge/index.json'))
    admitted=0
    for card in index.get('cards',[]):
        if task_id not in card.get('tasks',[]) and '*' not in card.get('tasks',[]):continue
        if card.get('state')!='VERIFIED':continue
        refs=card.get('evidence',[])
        valid=bool(refs)
        for ev in refs:
            p=safe_path(root,ev['path'])
            if not p.is_file() or file_hash(p)!=ev['sha256']:valid=False
        if not valid:stale.append(card['id']);continue
        if admitted<3:candidates.append(card['path']);admitted+=1
    for rel in dict.fromkeys(candidates):
        p=safe_path(root,rel)
        if not p.is_file():raise HarnessError('CONTEXT_MISSING',rel)
        body='\n## '+rel+'\n'+p.read_text(encoding='utf-8')+'\n'
        # Reserve space for the list of deferred sources, never silently truncate text.
        if len((text+body).encode())+len(('Deferred: '+str(candidates)).encode())<=max_bytes:
            text+=body;included.append(rel)
        else:deferred.append(rel)
    if deferred:text+='\nDeferred normative/context files (read explicitly before relevant changes):\n'+'\n'.join(deferred)+'\n'
    if len(text.encode())>max_bytes:raise HarnessError('CONTEXT_BUDGET','source index exceeds budget')
    return {'task':task_id,'text':text,'bytes':len(text.encode()),'included':included,'deferred':deferred,'stale_knowledge':stale,'source_references_digest':digest([{'path':p,'sha256':file_hash(safe_path(root,p))} for p in included+deferred]),'token_count':'NOT_MEASURED'}
