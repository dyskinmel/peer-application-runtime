"""Finite missing-frontier planning over authenticated read-only sessions.

Unseen encrypted records do not reveal their transitive dependencies. A proposal
covers only this observed frontier; accepting it never executes a fetch or apply.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
import hashlib
from product.wp04 import exchange as x
from product.wp09.par_secure_transport import PeerBinding, ReadSession
from .plan import FetchPlan
from .persistence import FetchError, require
from .client import error_code

PROFILE = 'par-dependency-proposal-local-0046'

def targets_owned(targets):
    require(type(targets) in (tuple, list) and 1 <= len(targets) <= 64, 'TARGETS_INVALID')
    result = tuple(targets)
    require(all(type(e) is bytes and len(e) == 32 for e in result), 'TARGETS_INVALID')
    require(len(set(result)) == len(result), 'TARGETS_INVALID')
    return tuple(sorted(result))

def source_guard(source, binding, inbox_generation, generation):
    require(type(source) is x.Source and type(binding) is PeerBinding, 'PLANNER_INPUT')
    require(tuple(source.scope) == binding.scope, 'PLAN_SCOPE')
    require(source.box._metadata['generation'] == inbox_generation, 'INBOX_GENERATION')
    value = generation()
    require(type(value) is int and value == binding.generation, 'STALE_GENERATION')
    try:
        source.authorize(binding.certificate)
        return source.guard(binding.certificate)
    except FetchError:
        raise
    except Exception as exc:
        raise FetchError(error_code(exc)) from None

@dataclass(frozen=True, slots=True)
class DependencyProposal:
    targets: tuple
    binding: PeerBinding
    inbox_generation: str
    local_revision: bytes
    plan: FetchPlan | None
    queries: int
    _source: x.Source = field(repr=False, compare=False)

    @property
    def state(self):
        return 'NO_FETCH_REQUIRED' if self.plan is None else 'FETCH_PROPOSED'

    @property
    def digest(self):
        raw = x.pack({0: PROFILE, 1: list(self.targets), 2: self.local_revision,
                      3: self.inbox_generation, 4: list(self.binding.scope),
                      5: self.binding.peer_id, 6: self.binding.peer_sha256,
                      7: self.binding.generation, 8: self.binding.certificate,
                      9: self.plan.to_bytes() if self.plan is not None else None}, 65536)
        return hashlib.sha256(raw).hexdigest()

    def accept(self, source, current_generation):
        """Recheck the owner observation, then return an unexecuted immutable plan."""
        require(source is self._source and callable(current_generation), 'PLAN_OWNER')
        current = source_guard(source, self.binding, self.inbox_generation, current_generation)
        require(current == self.local_revision, 'LOCAL_VIEW_CHANGED')
        return self.plan

class DependencyPlanner:
    def __init__(self, source, binding, current_generation):
        require(type(source) is x.Source and type(binding) is PeerBinding and
                callable(current_generation), 'PLANNER_INPUT')
        self.source = source
        self.binding = binding
        self._generation = current_generation
        self._inbox_generation = source.box._metadata['generation']
        self._busy = False
        self._guard()

    def _guard(self, revision=None):
        current = source_guard(self.source, self.binding, self._inbox_generation, self._generation)
        require(revision is None or current == revision, 'LOCAL_VIEW_CHANGED')
        return current

    @staticmethod
    def _cancel(cancel):
        require(cancel is None or isinstance(cancel, asyncio.Event), 'INVALID_CANCEL')
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError
        require(cancel is None or not cancel.is_set(), 'CANCELLED')

    async def _open(self, factory, cancel):
        self._cancel(cancel)
        opening = asyncio.ensure_future(factory())
        watcher = asyncio.create_task(cancel.wait()) if cancel is not None else None
        children = [opening] + ([watcher] if watcher is not None else [])
        try:
            await asyncio.wait(children, return_when=asyncio.FIRST_COMPLETED)
            self._cancel(cancel)
            if watcher is not None:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            self._cancel(cancel)
            result = opening.result()
            require(type(result) is ReadSession, 'SESSION_REQUIRED')
            return result
        except BaseException:
            for child in children:
                if not child.done():
                    child.cancel()
            await asyncio.gather(*children, return_exceptions=True)
            # A trusted, cooperative factory may return just as cancellation won.
            if opening.done() and not opening.cancelled() and opening.exception() is None:
                late = opening.result()
                if type(late) is ReadSession:
                    await late.stream.close()
            raise

    async def build(self, targets, open_session, *, max_records=64, max_bytes=8388608,
                    page_size=16, max_queries=32, timeout=30.0, cancel=None):
        require(not self._busy, 'PLANNER_BUSY')
        roots = targets_owned(targets)
        require(callable(open_session), 'SESSION_FACTORY')
        for value, upper in ((max_records, 64), (max_bytes, 8388608),
                             (page_size, x.MAX_PAGE), (max_queries, 32)):
            require(type(value) is int and 1 <= value <= upper, 'PLAN_BUDGET')
        require(type(timeout) in (int, float) and .05 <= timeout <= 120, 'INVALID_TIMEOUT')
        self._cancel(cancel)
        self._busy = True
        deadline = asyncio.get_running_loop().time() + timeout
        revision = None
        try:
            revision = self._guard()
            missing, previous = set(), set()
            for eid in roots:
                view = self.source.box.inspect(eid)
                require(view['state'] != 'NOT_OBSERVED', 'TARGET_NOT_OBSERVED')
                require(view['state'] in ('WAITING_DEPENDENCIES', 'READY_FOR_CORE'), view['state'])
                missing.update(bytes.fromhex(v) for v in view['missing'])
                previous.update(bytes.fromhex(v) for v in view['missingPrevious'])
            self._guard(revision)
            require(len(missing) <= max_records and len(previous) <= max_records, 'PLAN_RECORD_BUDGET')
            self._cancel(cancel)
            require(asyncio.get_running_loop().time() < deadline, 'PLAN_TIMEOUT')
            if not missing and not previous:
                return DependencyProposal(roots, self.binding, self._inbox_generation,
                                          revision, None, 0, self.source)
            snapshot = None
            queries = 0
            selected, by_envelope = {}, {}

            def insert(row):
                d = tuple(row)
                require(d[0] not in selected or selected[d[0]] == d, 'DESCRIPTOR_EQUIVOCATION')
                require(d[1] not in by_envelope or by_envelope[d[1]] == d, 'DESCRIPTOR_EQUIVOCATION')
                selected[d[0]] = d
                by_envelope[d[1]] = d
                require(len(selected) <= max_records, 'PLAN_RECORD_BUDGET')
                require(sum(r[2] for r in selected.values()) <= max_bytes, 'PLAN_BYTE_BUDGET')

            async def query(method, args):
                nonlocal queries, snapshot
                self._cancel(cancel)
                self._guard(revision)
                require(queries < max_queries, 'QUERY_BUDGET')
                queries += 1
                session = await self._open(open_session, cancel)
                try:
                    self._guard(revision)
                    self._cancel(cancel)
                    require(session.source is self.source and session.binding == self.binding, 'SESSION_BINDING')
                    session._authority_guard()
                    value = await session.request(method, args, cancel=cancel)
                    owned = x.unpack(x.pack(value, x.MAX_RESPONSE), x.MAX_RESPONSE)
                    x.response_value(method, args, owned)
                finally:
                    await session.stream.close()
                self._cancel(cancel)
                self._guard(revision)
                if snapshot is None:
                    snapshot = owned[0]
                require(owned[0] == snapshot, 'REMOTE_VIEW_CHANGED')
                return owned

            async with asyncio.timeout_at(deadline):
                ordered = sorted(missing)
                for offset in range(0, len(ordered), page_size):
                    page = await query('need', ordered[offset:offset + page_size])
                    for _, row in page[1]:
                        require(row is not None, 'DEPENDENCY_NOT_OFFERED')
                        insert(row)
                if previous - set(by_envelope):
                    offset, total, last = 0, None, None
                    seen_inner, seen_envelope = set(), set()
                    while True:
                        page = await query('have', {0: snapshot, 1: offset, 2: page_size})
                        require(total is None or total == page[4], 'CATALOG_CHANGED')
                        total = page[4]
                        for row in page[2]:
                            d = tuple(row)
                            require(last is None or last < d, 'CATALOG_ORDER')
                            require(d[0] not in seen_inner and d[1] not in seen_envelope, 'DESCRIPTOR_EQUIVOCATION')
                            seen_inner.add(d[0]); seen_envelope.add(d[1]); last = d
                            if d[1] in previous:
                                insert(d)
                        if page[3] is None:
                            break
                        offset = page[3]
                    require(previous <= set(by_envelope), 'PREDECESSOR_NOT_OFFERED')
                # Final remote snapshot check. This is a sender observation, not
                # a proof of global completeness or future snapshot freshness.
                await query('have', {0: snapshot, 1: 0, 2: 1})
                self._cancel(cancel)
                self._guard(revision)
                require(asyncio.get_running_loop().time() < deadline, 'PLAN_TIMEOUT')
                plan = FetchPlan(self.source.scope, snapshot, sorted(selected.values()), self.binding,
                                 self._inbox_generation, max_records, max_bytes)
                return DependencyProposal(roots, self.binding, self._inbox_generation,
                                          revision, plan, queries, self.source)
        except TimeoutError:
            raise FetchError('PLAN_TIMEOUT') from None
        except FetchError:
            raise
        except Exception as exc:
            raise FetchError(error_code(exc)) from None
        finally:
            self._busy = False
