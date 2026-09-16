#!/usr/bin/env python3
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from harness.public_preview import scan_public_surface

def read(p): return json.loads((ROOT/p).read_text(encoding='utf-8'))
def task(tid): return next(t for t in read('plan/tasks.json')['tasks'] if t['id']==tid)
errors=[]
try:
    mapping=read('plan/OWNER_CANDIDATE_MAPPING_0060.json')
    if set(mapping['owners'])!={f'WP-{i:02d}' for i in range(1,7)}: errors.append('OWNER_SET')
    candidates={t['id'] for t in read('plan/tasks.json')['tasks'] if t['status']=='CANDIDATE_IMPLEMENTED' and t['kind']=='EXPERIMENT'}
    mapped={x for o in mapping['owners'].values() for x in o['candidate_tasks']}
    if candidates-mapped: errors.append('UNMAPPED_CANDIDATES:'+','.join(sorted(candidates-mapped)))
    if task('H0-SELFTEST')['status']!='CANDIDATE_IMPLEMENTED': errors.append('H0_STATUS')
    for i in range(1,7):
        if task(f'L-WP{i:02d}')['status']!='PARTIAL_IMPLEMENTED': errors.append(f'L-WP{i:02d}_STATUS')
    for i in (1,2,3,5,6):
        if task(f'V-WP{i:02d}')['status']!='PLANNED': errors.append(f'V-WP{i:02d}_PROMOTED')
    if task('V-WP04')['status']!='PARTIAL_VERIFICATION_REGISTERED': errors.append('V-WP04_STATUS')
    if task('L-WP15')['status']!='PARTIAL_IMPLEMENTED' or task('V-WP15')['status']!='PARTIAL_VERIFICATION_REGISTERED': errors.append('WP15_STATUS')
    state=read('plan/product-state.json')
    if set(state['gates'].values())!={'NOT_RUN'} or state['native_runtime']!='NOT_STARTED' or state['independent_review']!='NOT_RUN': errors.append('FALSE_QUALIFICATION')
    v=read('plan/V_WP04_LOCAL_CLOSURE_0060.json')
    if not (v['local_result']=='PASS' and v['passed_check_count']==v['registered_check_count']==21 and not v['real_crdt_executed']): errors.append('VWP04_CLOSURE')
    hand=read('plan/DEVICE_HANDOFF_MANIFEST_0060.json')
    if len(hand['device_required'])!=10 or len(hand['external_required'])!=6: errors.append('HANDOFF_COUNTS')
    if any(not x['local_promotion_forbidden'] for k in ('device_required','external_required') for x in hand[k]): errors.append('HANDOFF_PROMOTION')
    legacy_policy=read('policy/public-preview-boundary.json')
    current_policy=read('oss/PUBLIC_SOURCE_POLICY.json')
    scan=scan_public_surface(ROOT,current_policy)
    if not scan['pass']: errors.append('PUBLIC_SCAN')
    if legacy_policy['publishable'] or len(legacy_policy['unresolved_gates'])!=5: errors.append('PUBLIC_GATE')
    if current_policy['publishable'] or len(current_policy['unresolved_gates'])!=7: errors.append('CURRENT_PUBLIC_GATE')
    comp=read('plan/LOCAL_COMPLETION_0060.json')
    if comp['product_gates_passed']!=0 or comp['production_ready'] or comp['sprint_a']['candidate_consolidation_is_product_credit']: errors.append('COMPLETION_CLAIM')
except Exception as e:
    errors.append('EXCEPTION:'+repr(e))
out={'result':'PASS' if not errors else 'FAIL','errors':errors,'product_qualified':False,'public_preview_publishable':False}
print(json.dumps(out,indent=2,sort_keys=True))
raise SystemExit(0 if not errors else 1)
