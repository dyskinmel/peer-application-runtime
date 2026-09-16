"""Bounded local Keeper candidate; not a network service or durable SLA."""
from .errors import KeeperError
from .contract import Authority,METHODS,issue_capability,verify_capability,make_call,verify_call,capability_id,reserve_payload,put_payload,verify_receipt
from .clock import Tick,BootClock
from .store import Keeper
from .service import AuthorizedProvider
