"""An intentionally restricted CDDL interpreter for the frozen input's grammar.

This is not an independently certified RFC 8610 implementation. Unsupported syntax
fails closed. Shape conformance is separate from crypto/authentication/CRDT checks.
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
import re
from .errors import WireError
from .codec import U64

ROOT = Path(__file__).resolve().parents[3]
TOKEN = re.compile(r'\s+|;[^\n]*|\.size|\.\.|[A-Za-z][A-Za-z0-9-]*|[0-9]+|[={}\[\]():,/*?]')


class Schema:
    def __init__(self, rules):
        self.rules = rules

    def validate(self, rule: str, value) -> None:
        if rule not in self.rules:
            raise WireError('CDDL_REFERENCE', rule)
        self._validate(self.rules[rule], value, rule, 0)

    def _validate(self, node, value, path, depth):
        if depth > 128:
            raise WireError('RESOURCE_LIMIT')
        kind = node[0]
        valid = True
        if kind == 'ref':
            name = node[1]
            if name == 'uint': valid = type(value) is int and 0 <= value <= U64
            elif name == 'bstr': valid = type(value) is bytes
            elif name == 'tstr': valid = type(value) is str
            elif name == 'bool': valid = type(value) is bool
            elif name == 'null': valid = value is None
            else:
                if name not in self.rules: raise WireError('CDDL_REFERENCE', name)
                if name == 'app-id' and type(value) is str and '\0' in value:
                    raise WireError('IDENTIFIER', path)
                return self._validate(self.rules[name], value, path, depth+1)
        elif kind == 'literal': valid = type(value) is int and value == node[1]
        elif kind == 'range': valid = type(value) is int and node[1] <= value <= node[2]
        elif kind == 'size':
            self._validate(node[1], value, path, depth+1)
            try:
                n = len(value.encode('utf-8', errors='strict')) if type(value) is str else len(value)
            except (UnicodeEncodeError,TypeError) as exc:
                raise WireError('SCHEMA', path) from exc
            valid = node[2] <= n <= node[3]
        elif kind == 'union':
            for child in node[1]:
                try:
                    self._validate(child, value, path, depth+1)
                    return
                except WireError as exc:
                    if exc.code not in ('SCHEMA',): raise
            valid = False
        elif kind == 'array':
            valid = type(value) is list and node[1] <= len(value) <= node[2]
            if valid:
                for i, child in enumerate(value):
                    self._validate(node[3], child, path+'['+str(i)+']', depth+1)
        elif kind == 'map':
            fields = {n: (optional, child) for n, optional, child in node[1]}
            valid = type(value) is dict and all(type(k) is int for k in value)
            if valid:
                valid = not set(value)-fields.keys() and all(o or k in value for k,(o,_) in fields.items())
            if valid:
                for k,v in value.items():
                    self._validate(fields[k][1], v, path+'.'+str(k), depth+1)
        else:
            raise WireError('CDDL_UNSUPPORTED')
        if not valid:
            raise WireError('SCHEMA', path)


def parse_cddl(text: str) -> Schema:
    """Parse all of this draft, never a silently accepted prefix."""
    if len(text) > 131072:
        raise WireError('LIMIT')
    tokens=[]; pos=0
    while pos<len(text):
        m=TOKEN.match(text,pos)
        if not m: raise WireError('CDDL_UNSUPPORTED')
        tok=m.group(); pos=m.end()
        if not tok.isspace() and not tok.startswith(';'):tokens.append(tok)
    i=0
    def peek(): return tokens[i] if i<len(tokens) else None
    def pop(expected=None):
        nonlocal i
        if i>=len(tokens) or (expected is not None and tokens[i]!=expected):raise WireError('CDDL_SYNTAX')
        t=tokens[i];i+=1;return t
    def bounds(node):
        if node[0]=='literal':return node[1],node[1]
        if node[0]=='range':return node[1],node[2]
        raise WireError('CDDL_UNSUPPORTED')
    def expr(level=0):
        if level>64:raise WireError('CDDL_SYNTAX')
        nodes=[atom(level+1)]
        while peek()=='/':pop('/');nodes.append(atom(level+1))
        return nodes[0] if len(nodes)==1 else ('union',nodes)
    def atom(level):
        t=pop()
        if t=='(':
            node=expr(level+1);pop(')')
        elif t=='{':
            fields=[];keys=set()
            while peek()!='}':
                opt=peek()=='?'
                if opt:pop('?')
                k=pop()
                if not k.isdigit() or int(k) in keys:raise WireError('CDDL_SYNTAX')
                k=int(k);keys.add(k);pop(':');fields.append((k,opt,expr(level+1)))
                if peek()==',':pop(',')
                elif peek()!='}':raise WireError('CDDL_SYNTAX')
            pop('}');node=('map',fields)
        elif t=='[':
            lo=0
            if peek() and peek().isdigit():lo=int(pop())
            pop('*')
            if not peek() or not peek().isdigit():raise WireError('CDDL_UNSUPPORTED')
            hi=int(pop());child=expr(level+1);pop(']')
            if lo>hi:raise WireError('CDDL_SYNTAX')
            node=('array',lo,hi,child)
        elif t.isdigit():
            n=int(t);node=('literal',n)
            if peek()=='..':
                pop('..');end=pop()
                if not end.isdigit() or int(end)<n:raise WireError('CDDL_SYNTAX')
                node=('range',n,int(end))
        elif re.fullmatch('[A-Za-z][A-Za-z0-9-]*',t):node=('ref',t)
        else:raise WireError('CDDL_SYNTAX')
        if peek()=='.size':
            pop('.size');size=atom(level+1);lo,hi=bounds(size);node=('size',node,lo,hi)
        return node
    rules={}
    while i<len(tokens):
        name=pop()
        if not re.fullmatch('[A-Za-z][A-Za-z0-9-]*',name) or name in rules:raise WireError('CDDL_SYNTAX')
        pop('=');rules[name]=expr()
    def refs(n):
        if n[0]=='ref':return {n[1]}
        if n[0]=='size':return refs(n[1])
        if n[0]=='array':return refs(n[3])
        if n[0]=='union':return set().union(*(refs(x) for x in n[1]))
        if n[0]=='map':return set().union(*(refs(x[2]) for x in n[1]))
        return set()
    primitives={'uint','bstr','tstr','bool','null'}
    visiting=set();done=set()
    def walk(name):
        if name in done or name in primitives:return
        if name in visiting:raise WireError('CDDL_UNSUPPORTED','recursive rule')
        if name not in rules:raise WireError('CDDL_REFERENCE',name)
        visiting.add(name)
        for ref in refs(rules[name]):walk(ref)
        visiting.remove(name);done.add(name)
    for name in rules:walk(name)
    return Schema(rules)


@lru_cache(maxsize=1)
def default_schema() -> Schema:
    return parse_cddl((ROOT/'baseline/spec-00.02.00/protocol/par-v1.cddl').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def registry() -> dict:
    import json
    return json.loads((ROOT/'baseline/spec-00.02.00/protocol/registry.json').read_text(encoding='utf-8'))


def validate_frame(value) -> None:
    if type(value) is not dict or any(type(k) is not int for k in value):
        raise WireError('SCHEMA','frame')
    code=value.get(1)
    if type(code) is not int:raise WireError('SCHEMA','message code')
    entries={row['code']:row for row in registry()['messages']}
    if code not in entries:raise WireError('MESSAGE_TYPE')
    name=entries[code]['body_type'].replace('-body','-frame')
    default_schema().validate(name,value)
    b=value[4]
    # Explicit candidate semantic overlay, see ADR-WIRE-0001. No signature verification.
    if code==1:
        label = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
        if not re.fullmatch(label + r'(?:\.' + label + r')+', b[0]):
            raise WireError('IDENTIFIER', 'app-id')
        if len(b[3])!=len(set(b[3])) or len(b[4])!=len(set(b[4])) or any(not x or '\0' in x for x in b[3]):
            raise WireError('NEGOTIATION')
    if code==10 and value[3]!=b[0]:raise WireError('SPACE_BINDING')
    page_fields={13:(1,2,3),20:(2,1,3),41:(2,3,4)}
    if code in page_fields:
        items,cursor,done=page_fields[code]
        if b[done] != (b[cursor] is None) or (not b[done] and not b[items]):raise WireError('PAGE_STATE')
    if code==60 and '\0' in b[2]:raise WireError('IDENTIFIER','handler')
    if code==255 and '\0' in b[1]:raise WireError('IDENTIFIER','phase')
