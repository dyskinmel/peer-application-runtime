"""Owner grants, strict addresses and bounded resolver output: no network calls."""
import dataclasses
import unittest
from product.wp09 import par_connectivity as api

PUBLIC = 'tcp://8.8.8.8:443'
DNS = 'tcp://peer.invalid:443'

def grant(endpoint=PUBLIC, **kw):
    return api.RouteGrant(endpoint=endpoint, peer_id='peer-A', source='manual', networks=('0.0.0.0/0', '::/0'), **kw)

def policy(*grants, **kw):
    return api.Policy(grants=grants, allow_egress=True, **kw)

class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(api, 'parse_endpoint', None)), 'local connectivity policy is not implemented')

    def rejects(self, code, fn, *args, **kw):
        with self.assertRaises(api.ConnectivityError) as cm: fn(*args, **kw)
        self.assertEqual(cm.exception.code, code)
        self.assertEqual(str(cm.exception), code)

    def test_empty_default_is_no_egress(self):
        p=api.Policy();self.assertFalse(p.allow_egress);self.assertEqual(p.grants, ())
        self.rejects('EGRESS_DENIED',api.select_candidates,(),p)

    def test_empty_explicit_list_stays_empty(self):
        self.assertEqual(api.select_candidates((),policy()),())

    def test_numeric_target_is_canonical_and_has_no_dns_name(self):
        g=grant();t=api.authorize_addresses(g,None,policy(g),7)
        self.assertEqual((t[0].ip,t[0].port,t[0].server_name,t[0].generation),('8.8.8.8',443,None,7))

    def test_ipv6_is_compressed(self):
        e=api.parse_endpoint('quic://[2606:4700:4700:0000:0000:0000:0000:1111]:443')
        self.assertEqual(e.key,'quic://[2606:4700:4700::1111]:443')

    def test_mapped_ipv6_is_ipv4(self):
        self.assertEqual(api.parse_endpoint('tcp://[::ffff:8.8.8.8]:443').key,PUBLIC)

    def test_duplicate_candidates_are_one(self):
        g=grant();p=policy(g)
        rows=(api.Candidate(PUBLIC,'peer-A'),api.Candidate('tcp://[::ffff:8.8.8.8]:443','peer-A'))
        self.assertEqual(api.select_candidates(rows,p),(g,))

    def test_peer_is_bound_to_grant(self):
        self.rejects('ROUTE_NOT_GRANTED',api.select_candidates,(api.Candidate(PUBLIC,'peer-B'),),policy(grant()))

    def test_source_is_bound_to_grant(self):
        self.rejects('ROUTE_NOT_GRANTED',api.select_candidates,(api.Candidate(PUBLIC,'peer-A','helper'),),policy(grant()))

    def test_unknown_source_is_invalid(self):
        self.rejects('INVALID_SOURCE',api.Candidate,PUBLIC,'peer-A','automatic-stun')

    def test_policy_copies_mutable_grants(self):
        items=[grant()];p=api.Policy(grants=items,allow_egress=True);items.clear()
        self.assertEqual(len(p.grants),1)
        with self.assertRaises(dataclasses.FrozenInstanceError):p.allow_egress=False

    def test_invalid_cidr_fails_at_owner_registration(self):
        self.rejects('INVALID_NETWORK',api.RouteGrant,PUBLIC,'peer-A','manual',('10.0.0.1/8',))

    def test_empty_networks_never_allow_destination(self):
        g=api.RouteGrant(PUBLIC,'peer-A','manual',())
        self.rejects('ADDRESS_NOT_GRANTED',api.authorize_addresses,g,None,policy(g),0)

    def test_local_exception_requires_local_flag_and_cidr(self):
        g=grant('tcp://192.168.1.10:4000')
        self.rejects('LOCAL_ADDRESS_DENIED',api.authorize_addresses,g,None,policy(g),0)
        yes=api.RouteGrant(g.endpoint,'peer-A','manual',('192.168.1.0/24',),True)
        self.assertEqual(api.authorize_addresses(yes,None,policy(yes),0)[0].ip,'192.168.1.10')
        no=dataclasses.replace(yes,networks=('192.168.2.0/24',))
        self.rejects('ADDRESS_NOT_GRANTED',api.authorize_addresses,no,None,policy(no),0)

    def test_dns_requires_explicit_resolver(self):
        g=grant(DNS);self.rejects('DNS_NOT_GRANTED',api.authorize_addresses,g,None,policy(g),0)

    def test_dns_success_checks_all_and_pins_numbers(self):
        g=grant(DNS,resolver_id='owner-dns')
        r=api.Resolution('peer.invalid','owner-dns',('8.8.8.8','2606:4700:4700::1111'))
        t=api.authorize_addresses(g,r,policy(g),3)
        self.assertEqual([x.ip for x in t],['8.8.8.8','2606:4700:4700::1111'])
        self.assertTrue(all(x.server_name=='peer.invalid' and x.generation==3 for x in t))

    def test_one_forbidden_dns_answer_rejects_entire_response(self):
        g=grant(DNS,resolver_id='owner-dns');r=api.Resolution('peer.invalid','owner-dns',('8.8.8.8','127.0.0.1'))
        self.rejects('LOCAL_ADDRESS_DENIED',api.authorize_addresses,g,r,policy(g),0)

    def test_mapped_forbidden_dns_answer_is_not_public(self):
        g=grant(DNS,resolver_id='owner-dns');r=api.Resolution('peer.invalid','owner-dns',('::ffff:127.0.0.1',))
        self.rejects('LOCAL_ADDRESS_DENIED',api.authorize_addresses,g,r,policy(g),0)

    def test_dns_resolver_identity_bound(self):
        g=grant(DNS,resolver_id='owner-dns');r=api.Resolution('peer.invalid','other',('8.8.8.8',))
        self.rejects('RESOLUTION_MISMATCH',api.authorize_addresses,g,r,policy(g),0)

    def test_dns_name_is_exact_not_suffix(self):
        g=grant(DNS,resolver_id='owner-dns');r=api.Resolution('evil.peer.invalid','owner-dns',('8.8.8.8',))
        self.rejects('RESOLUTION_MISMATCH',api.authorize_addresses,g,r,policy(g),0)

    def test_aliases_must_all_be_explicit_and_acyclic(self):
        g=grant(DNS,resolver_id='owner-dns',aliases=('alias.invalid','next.invalid'))
        r=api.Resolution('peer.invalid','owner-dns',('8.8.8.8',),('alias.invalid','next.invalid'))
        self.assertEqual(len(api.authorize_addresses(g,r,policy(g),0)),1)
        self.rejects('DNS_ALIAS_DENIED',api.authorize_addresses,g,dataclasses.replace(r,aliases=('evil.invalid',)),policy(g),0)
        self.rejects('DNS_ALIAS_CYCLE',api.authorize_addresses,g,dataclasses.replace(r,aliases=('alias.invalid','alias.invalid')),policy(g),0)

    def test_dns_address_duplicates_count_before_dedup(self):
        g=grant(DNS,resolver_id='owner-dns');r=api.Resolution('peer.invalid','owner-dns',('8.8.8.8',)*3)
        self.rejects('ADDRESS_BUDGET',api.authorize_addresses,g,r,policy(g,max_addresses=2),0)

    def test_dns_alias_hop_budget(self):
        g=grant(DNS,resolver_id='owner-dns',aliases=tuple(f'a{i}.invalid' for i in range(5)))
        r=api.Resolution('peer.invalid','owner-dns',('8.8.8.8',),g.aliases)
        self.rejects('DNS_ALIAS_BUDGET',api.authorize_addresses,g,r,policy(g),0)

    def test_no_answers_is_not_reachability_success(self):
        g=grant(DNS,resolver_id='owner-dns')
        self.rejects('NO_ADDRESSES',api.authorize_addresses,g,api.Resolution('peer.invalid','owner-dns',()),policy(g),0)

    def test_candidates_budget_precedes_dedup(self):
        g=grant();self.rejects('CANDIDATE_BUDGET',api.select_candidates,(api.Candidate(PUBLIC,'peer-A'),)*3,policy(g,max_candidates=2))

    def test_total_candidate_bytes_bound(self):
        g=grant();self.rejects('CANDIDATE_BYTES',api.select_candidates,(api.Candidate(PUBLIC,'peer-A'),),policy(g,max_candidate_bytes=8))

    def test_policy_duplicate_grants_rejected(self):
        g=grant();self.rejects('DUPLICATE_GRANT',policy,g,g)

    def test_policy_bool_is_not_integer_budget(self):
        self.rejects('INVALID_BUDGET',api.Policy,max_attempts=True)

    def test_timeout_nan_rejected(self):
        self.rejects('INVALID_BUDGET',api.Policy,timeout=float('nan'))

    def test_invalid_types_and_unknown_candidate_fields(self):
        self.rejects('INVALID_ENDPOINT',api.parse_endpoint,b'tcp://8.8.8.8:443')
        self.rejects('INVALID_CANDIDATES',api.select_candidates,iter(()),policy())
        with self.assertRaises(TypeError):api.Candidate(PUBLIC,'peer-A',private_space_name='SENTINEL')

# Each vector has a stable independent test identity, not a hidden subtest count.
BAD_ENDPOINTS={
 'credential':'tcp://u:p@8.8.8.8:443','path':'tcp://8.8.8.8:443/a','slash':'tcp://8.8.8.8:443/',
 'query':'tcp://8.8.8.8:443?x=1','fragment':'tcp://8.8.8.8:443#x','percent':'tcp://%38.8.8.8:443',
 'zone':'tcp://[fe80::1%eth0]:443','unbracketed':'tcp://2606:4700::1:443','integer':'tcp://2130706433:443',
 'hex':'tcp://0x7f000001:443','short_ipv4':'tcp://127.1:443','octal':'tcp://0177.0.0.1:443',
 'bad_ipv4':'tcp://999.1.1.1:443','newline':'tcp://8.8.8.8:443\n','space':' tcp://8.8.8.8:443',
 'missing_port':'tcp://peer.invalid','zero_port':'tcp://8.8.8.8:0','huge_port':'tcp://8.8.8.8:65536',
 'leading_port':'tcp://8.8.8.8:0443','unknown_scheme':'http://8.8.8.8:443','unicode':'tcp://p\u00e9er.invalid:443',
 'trailing_dot':'tcp://peer.invalid.:443','underscore':'tcp://_peer.invalid:443','backslash':'tcp://8.8.8.8:443\\',
 'empty':'','long':'tcp://'+'a'*254+'.invalid:443','localhost':'tcp://localhost:443','emptylabel':'tcp://x..invalid:443',
}
DENIED_IPS={
 'loopback':'127.0.0.1','rfc1918_10':'10.1.2.3','rfc1918_172':'172.16.2.3','rfc1918_192':'192.168.1.1',
 'metadata4':'169.254.169.254','linklocal4':'169.254.1.2','cgnat':'100.64.1.2','metadata_cgnat':'100.100.100.200',
 'unspecified4':'0.0.0.0','thisnetwork':'0.1.2.3','multicast4':'224.0.0.1','reserved4':'240.0.0.1','broadcast':'255.255.255.255',
 'docs4a':'192.0.2.1','docs4b':'198.51.100.1','docs4c':'203.0.113.1','benchmark':'198.18.0.1','protocol4':'192.0.0.9',
 'loopback6':'::1','unspecified6':'::','linklocal6':'fe80::1','ula':'fd01::1','metadata6':'fd00:ec2::254',
 'multicast6':'ff02::1','docs6':'2001:db8::1','docs6_new':'3fff::1','translation':'64:ff9b::808:808',
 'translation_local':'64:ff9b:1::1','six_to_four':'2002:0808:0808::1','teredo':'2001::1','site_local':'fec0::1',
 'dummy6':'100:0:0:1::1','discard6':'100::1','srv6':'5f00::1',
}
def bad_endpoint(value):
    def test(self):self.rejects('INVALID_ENDPOINT',api.parse_endpoint,value)
    return test
for name,value in BAD_ENDPOINTS.items():setattr(PolicyTests,'test_invalid_endpoint_'+name,bad_endpoint(value))
def bad_ip(ip):
    def test(self):
        ep=f'tcp://[{ip}]:443' if ':' in ip else f'tcp://{ip}:443';g=grant(ep)
        with self.assertRaises(api.ConnectivityError):api.authorize_addresses(g,None,policy(g),0)
    return test
for name,value in DENIED_IPS.items():setattr(PolicyTests,'test_denied_address_'+name,bad_ip(value))
