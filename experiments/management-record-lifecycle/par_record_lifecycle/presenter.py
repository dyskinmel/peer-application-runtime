"""UI-independent diagnostics. No deletion command and no invented percentage."""
from . import contracts as c


def present(inventory) -> dict:
    v = c.decode_inventory(c.encode_inventory(inventory))
    p = c.plan(v)
    ledgers = {}
    unresolved = 0
    for kind in c.STATES:
        records = [r for r in v['records'] if r['kind'] == kind]
        pending = sum(r['state'] not in c.TERMINAL[kind] for r in records)
        unresolved += pending
        ledgers[kind] = {'records': len(records), 'unresolved': pending,
                         'reserved_bytes': sum(r['reserved_bytes'] for r in records)}
    if unresolved:
        state = 'RESOLUTION_REQUIRED'
    elif not all(v['gates'].values()):
        state = 'MIGRATION_REQUIRED'
    elif p['model_ready']:
        state = 'MODEL_ELIGIBLE'
    else:
        state = 'BLOCKED'
    return {'scope': 'DIAGNOSTIC_ONLY', 'state': state, 'message_key': 'lifecycle.'+state.lower(),
            'simulation': v['source'] == 'MODEL_FIXTURE', 'ledgers': ledgers,
            'reserved_bytes': sum(r['reserved_bytes'] for r in v['records']),
            'archive_bytes_estimate': p['archive_bytes_estimate'],
            'inventory_digest': p['inventory_digest'], 'blockers': p['blockers'],
            'can_delete': False, 'completion_percent': None,
            'allowed_actions': ['inspect_references', 'export_inventory'],
            'product_qualified': False}
