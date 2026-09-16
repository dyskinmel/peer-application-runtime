"""Explicit overlay; exact schema identity. Not a silent upgrade of old data."""
from pathlib import Path
from functools import lru_cache
import sqlite3
from par_store.store import Store
from par_store.model import sha
from par_store.schema import objects
DDL=Path(__file__).resolve().parents[1]/'schema.sql'
def sql():return Store.schema_sql()+'\n'+DDL.read_text()
def digest():return sha(Store.schema_profile()+b'auth-store-overlay-v1\x00'+DDL.read_bytes())
@lru_cache(maxsize=1)
def expected():
    c=sqlite3.connect(':memory:')
    try:c.executescript(sql());return objects(c)
    finally:c.close()
def matches(c):return objects(c)==expected()
def statements():
    current=''
    for line in DDL.read_text().splitlines(True):
        current+=line
        if sqlite3.complete_statement(current):yield current;current=''
    if current.strip():raise ValueError('incomplete migration SQL')
