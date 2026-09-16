"""Compare actual SQLite schema objects, not just user-controlled version metadata."""
from functools import lru_cache
import sqlite3

def objects(c):
    return [tuple(x) for x in c.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]

@lru_cache(maxsize=1)
def expected_objects():
    from .store import BASE_DDL,OVERLAY
    c=sqlite3.connect(':memory:')
    try:
        c.executescript(BASE_DDL.read_text()+'\n'+OVERLAY.read_text())
        return objects(c)
    finally:c.close()

def matches(c):return objects(c)==expected_objects()
