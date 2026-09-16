from pathlib import Path
from functools import lru_cache
import sqlite3
from par_auth_store.backend import BoundStorage
from par_store.schema import objects
from .model import sha
DDL=Path(__file__).resolve().parents[1]/'schema.sql'
def sql():return BoundStorage.schema_sql()+'\n'+DDL.read_text()
def digest():return sha(BoundStorage.schema_profile()+b'blob-store-overlay-v1\x00'+DDL.read_bytes())
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
