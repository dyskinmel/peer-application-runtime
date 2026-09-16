"""Bounded PAR subset of RFC 8949 deterministic CBOR, not a general CBOR codec.

Unsigned 64-bit integers, bytes, strict UTF-8, bool/null, arrays and uint-key maps.
No tags, floats, negative integers, indefinite forms or coercions are admitted.
The decoder validates canonical bytes BEFORE constructing a typed PAR message.
"""
from __future__ import annotations
from .errors import WireError

MAX_BYTES = 1_048_576
MAX_DEPTH = 32
MAX_NODES = 100_000  # local resource budget, NOT a new validity rule
U64 = (1 << 64) - 1


def _head(major: int, value: int) -> bytes:
    if not 0 <= value <= U64:
        raise WireError('UINT_RANGE')
    if value < 24:
        return bytes([(major << 5) | value])
    for ai, width in ((24,1),(25,2),(26,4),(27,8)):
        if value < 1 << (width * 8):
            return bytes([(major << 5) | ai]) + value.to_bytes(width, 'big')
    raise WireError('UINT_RANGE')


def encode(value, *, max_bytes: int = MAX_BYTES, max_nodes: int = MAX_NODES) -> bytes:
    """Canonical encoding with aggregate output, recursion and object-count budgets."""
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES or type(max_nodes) is not int or max_nodes < 1:
        raise ValueError('invalid encoder budget')
    out = bytearray()
    active: set[int] = set()
    nodes = 0

    def put(b):
        if len(out) + len(b) > max_bytes:
            raise WireError('LIMIT')
        out.extend(b)

    def item(v, depth):
        nonlocal nodes
        if depth > MAX_DEPTH:
            raise WireError('DEPTH')
        nodes += 1
        if nodes > max_nodes:
            raise WireError('RESOURCE_LIMIT')
        t = type(v)
        if v is None:
            put(b'\xf6')
        elif t is bool:
            put(b'\xf5' if v else b'\xf4')
        elif t is int:
            if v < 0:
                raise WireError('FORBIDDEN_TYPE')
            put(_head(0, v))
        elif t is bytes:
            put(_head(2, len(v))); put(v)
        elif t is str:
            # UTF-8 is at least one byte per Python codepoint. Bound before conversion.
            if len(v) > max_bytes:
                raise WireError('LIMIT')
            try:
                raw = v.encode('utf-8', errors='strict')
            except UnicodeEncodeError as exc:
                raise WireError('UTF8') from exc
            put(_head(3, len(raw))); put(raw)
        elif t in (list, dict):
            if id(v) in active:
                raise WireError('CYCLE')
            if len(v) > max_nodes:
                raise WireError('RESOURCE_LIMIT')
            active.add(id(v))
            try:
                if t is list:
                    put(_head(4, len(v)))
                    for child in v:
                        item(child, depth + 1)
                else:
                    if any(type(k) is not int or not 0 <= k <= U64 for k in v):
                        raise WireError('MAP_KEY')
                    put(_head(5, len(v)))
                    # For unsigned keys, numeric order equals bytewise encoding order.
                    for key in sorted(v):
                        item(key, depth + 1); item(v[key], depth + 1)
            finally:
                active.remove(id(v))
        else:
            raise WireError('FORBIDDEN_TYPE')
    item(value, 0)
    return bytes(out)


def decode(data: bytes, *, max_bytes: int = MAX_BYTES, max_nodes: int = MAX_NODES):
    """Consume exactly one item. No lossy re-encoding/canonicalization of invalid input."""
    if type(data) is not bytes:
        raise TypeError('decode requires immutable bytes')
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES or type(max_nodes) is not int or max_nodes < 1:
        raise ValueError('invalid decoder budget')
    if len(data) > max_bytes:
        raise WireError('LIMIT')
    pos = 0
    nodes = 0

    def take(n):
        nonlocal pos
        if n > len(data) - pos:
            raise WireError('TRUNCATED')
        b = data[pos:pos+n]; pos += n
        return b

    def argument(ai):
        if ai < 24:
            return ai
        if ai == 31:
            raise WireError('INDEFINITE')
        if ai not in (24,25,26,27):
            raise WireError('RESERVED')
        width = 1 << (ai - 24)
        n = int.from_bytes(take(width), 'big')
        minimum = (24, 256, 65536, 4294967296)[ai-24]
        if n < minimum:
            raise WireError('NON_MINIMAL')
        return n

    def item(depth):
        nonlocal nodes
        if depth > MAX_DEPTH:
            raise WireError('DEPTH')
        nodes += 1
        if nodes > max_nodes:
            raise WireError('RESOURCE_LIMIT')
        initial = take(1)[0]; major, ai = initial >> 5, initial & 31
        if major == 7:
            if ai in (20,21,22):
                return (False,True,None)[ai-20]
            raise WireError('FORBIDDEN_TYPE')
        if major not in (0,2,3,4,5):
            raise WireError('FORBIDDEN_TYPE')
        n = argument(ai)
        if major == 0:
            return n
        if n > max_bytes:
            raise WireError('LIMIT')
        if major in (2,3):
            b = take(n)
            if major == 2:
                return b
            try:
                return b.decode('utf-8', errors='strict')
            except UnicodeDecodeError as exc:
                raise WireError('UTF8') from exc
        needed = n * (2 if major == 5 else 1)
        if needed > len(data) - pos:
            raise WireError('TRUNCATED')
        if nodes + needed > max_nodes:
            raise WireError('RESOURCE_LIMIT')
        if major == 4:
            return [item(depth+1) for _ in range(n)]
        result = {}; previous = -1
        for _ in range(n):
            key = item(depth+1)
            if type(key) is not int:
                raise WireError('MAP_KEY')
            if key <= previous:
                raise WireError('MAP_ORDER')
            previous = key
            result[key] = item(depth+1)
        return result
    value = item(0)
    if pos != len(data):
        raise WireError('TRAILING')
    return value
