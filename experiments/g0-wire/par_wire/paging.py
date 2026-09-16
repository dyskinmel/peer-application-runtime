"""Local scoped inventory consistency helper; no trust/authentication is inferred.

The transport must bind requested_cursor to the actual request and authenticate the
Space. Draft-2's missing next-page request mapping remains an OPEN decision.
"""
from __future__ import annotations
import copy
from .errors import WireError
from .schema import validate_frame
from .codec import encode


class InventoryWalk:
    def __init__(self, *, space: bytes, token: bytes, max_items: int=65536, max_pages: int=4096, max_bytes: int=8_388_608):
        if any(type(x) is not bytes or len(x)!=32 for x in (space,token)):raise ValueError('invalid scope')
        if any(type(x) is not int or x<1 for x in (max_items,max_pages,max_bytes)):raise ValueError('invalid budget')
        self.space=space;self.token=token;self.max_items=max_items;self.max_pages=max_pages;self.max_bytes=max_bytes;self._bytes=0
        self._cursor=None;self._seen_cursors=set();self._items={};self._pages=0;self._state='INCOMPLETE'

    def append(self, page: dict, *, requested_cursor: bytes|None) -> None:
        if self._state!='INCOMPLETE':raise WireError('CLOSED')
        try:
            validate_frame(page)
            if page[1]!=20:raise WireError('MESSAGE_TYPE')
            if page[3]!=self.space:raise WireError('SPACE_BINDING')
            b=page[4]
            if b[0]!=self.token:raise WireError('SNAPSHOT_CHANGED')
            if requested_cursor!=self._cursor:raise WireError('CURSOR')
            next_cursor=b[1]
            if next_cursor is not None and next_cursor in self._seen_cursors:raise WireError('CURSOR_REPLAY')
            if self._pages+1>self.max_pages or len(self._items)+len(b[2])>self.max_items:
                raise WireError('RESOURCE_LIMIT')
            page_size=4+len(encode(page))
            if self._bytes+page_size>self.max_bytes:raise WireError('RESOURCE_LIMIT')
            new_ids=[x[0] for x in b[2]]
            if len(set(new_ids))!=len(new_ids) or self._items.keys()&set(new_ids):raise WireError('DUPLICATE_ITEM')
            # Check all conditions before mutating the candidate snapshot.
            for row in b[2]:self._items[row[0]]=copy.deepcopy(row)
            self._pages+=1;self._bytes+=page_size;self._cursor=next_cursor
            if next_cursor is not None:self._seen_cursors.add(next_cursor)
            if b[3]:self._state='PEER_SNAPSHOT_COMPLETE'
        except WireError:
            self._items.clear();self._state='INVALIDATED';raise

    def snapshot(self) -> dict:
        return {'space':self.space,'token':self.token,'coverage':self._state,
                'pages':self._pages,'encoded_bytes':self._bytes,'next_cursor':self._cursor,
                'items':copy.deepcopy(list(self._items.values())),
                'authenticated':False,'global_completeness':False}
