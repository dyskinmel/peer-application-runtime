"""Non-destructive local management-record lifecycle candidate."""
from .contracts import LifecycleError, encode_inventory, decode_inventory, plan
from .model import LifecycleModel
from .inventory import collect_inventory

from .presenter import present
