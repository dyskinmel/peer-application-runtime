"""Stage-specific retirement permission, separate from upload capabilities.

The trusted host supplies current Authority. Historical records can be checked
cryptographically but do not discover a newer authority or prevent whole-store
rollback. No administrator delegation is inferred from a reserve/put grant.
"""
from par_crypto.primitives import domain, hashed
from par_keeper.contract import authority_body, authority_from, split, verify_capability
from par_keeper_upload import protocol as upload
from par_keeper_service.errors import ServiceError as E

PROFILE = 'keeper-upload-retire-local-v1'
MAX_BYTES = 131072
MAX_REBINDS = 8
fixed, integer, keys = upload.fixed, upload.integer, upload.keys


def dump(value):
    return upload.dump(value, MAX_BYTES)


def load(raw):
    return upload.load(raw, MAX_BYTES)


def digest(raw):
    if type(raw) is not bytes or not raw or len(raw) > MAX_BYTES:
        raise E('RETIREMENT_SCHEMA')
    return hashed('keeper-upload-retire-local/bytes', [raw])


def signed(provider, seed, label, body):
    raw = dump(body)
    return dump({0: raw, 1: provider.sign(seed, domain('keeper-upload-retire-local/' + label, [raw]))})


def verified(provider, raw, label, public):
    outer = load(raw)
    keys(outer, (0, 1)); fixed(outer[1], 64); fixed(public)
    try:
        provider.verify(public, domain('keeper-upload-retire-local/' + label, [outer[0]]), outer[1])
    except Exception:
        raise E('RETIREMENT_SIGNATURE') from None
    return load(outer[0])


def version(body):
    integer(body[0], 1, 1)
    if body[1] != PROFILE:
        raise E('RETIREMENT_SCHEMA')


def origin(provider, raw):
    try:
        body = upload.check_command(provider, raw)
        if body[2] != 'begin':
            raise E('RETIREMENT_ORIGIN')
        cap, _ = split(body[4])
        old = authority_from(cap[2])
        verify_capability(provider, old, cap[3], body[4])
        return body, cap
    except E:
        raise
    except Exception:
        raise E('RETIREMENT_ORIGIN') from None


def _authority_order(old, new):
    # No change of application, Space or rollback of a known sequence/epoch.
    if (new[:2] != old[:2] or new[3] < old[3] or new[4] < old[4]
            or (new[3] == old[3] and new != old)):
        raise E('RETIREMENT_AUTHORITY_ORDER')


def _grant_shape(body):
    keys(body, range(9)); version(body)
    try:
        authority_from(body[2])
    except Exception:
        raise E('RETIREMENT_SCHEMA') from None
    for k in (3, 4, 5, 6, 7):
        fixed(body[k])
    if body[8] != 'RETIRE_STAGING_ONLY':
        raise E('RETIREMENT_SCHEMA')


def _grant(provider, raw):
    outer = load(raw); keys(outer, (0, 1))
    body = load(outer[0]); _grant_shape(body)
    return verified(provider, raw, 'grant', authority_from(body[2]).issuer)


def issue_grant(provider, issuer_seed, authority, keeper, begin, nonce):
    body, cap = origin(provider, begin)
    current = authority_body(authority)
    _authority_order(cap[2], current)
    fixed(keeper); fixed(nonce)
    if keeper != cap[3] or provider.sign_public(issuer_seed) != authority.issuer:
        raise E('RETIREMENT_GRANT_AUTH')
    grant = {0: 1, 1: PROFILE, 2: current, 3: keeper, 4: cap[4],
             5: upload.token_for(provider, begin), 6: digest(begin),
             7: nonce, 8: 'RETIRE_STAGING_ONLY'}
    _grant_shape(grant)
    return signed(provider, issuer_seed, 'grant', grant)


def make_request(provider, subject_seed, grant, operation):
    body = _grant(provider, grant); fixed(operation)
    if provider.sign_public(subject_seed) != body[4]:
        raise E('RETIREMENT_SUBJECT')
    return signed(provider, subject_seed, 'request',
                  {0: 1, 1: PROFILE, 2: grant, 3: operation, 4: True})


def inspect_request(provider, raw):
    outer = load(raw); keys(outer, (0, 1))
    request = load(outer[0]); keys(request, range(5)); version(request)
    fixed(request[3])
    if request[4] is not True:
        raise E('RETIREMENT_ACK_REQUIRED')
    grant = _grant(provider, request[2])
    verified(provider, raw, 'request', grant[4])
    return request, outer, grant


def check_request(provider, raw, begin, keeper, authority=None):
    request, outer, grant = inspect_request(provider, raw)
    body, cap = origin(provider, begin)
    fixed(keeper)
    if (grant[3], grant[4], grant[5], grant[6]) != (
            keeper, cap[4], upload.token_for(provider, begin), digest(begin)) or keeper != cap[3]:
        raise E('RETIREMENT_SCOPE')
    _authority_order(cap[2], grant[2])
    if authority is not None and grant[2] != authority_body(authority):
        raise E('STALE_AUTHORITY')
    return request, outer, grant


def request_id(provider, raw):
    request, _, grant = inspect_request(provider, raw)
    return hashed('keeper-upload-retire-local/operation', [grant[3], grant[4], request[3]])
