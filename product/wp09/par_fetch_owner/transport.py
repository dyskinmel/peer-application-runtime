"""Reuse existing bounded private descriptor framing; do not open a listener."""
from product.wp10.transport import _serve_service
from .owner import PROTOCOL, OPERATIONS

async def serve_fetch_connected(owner, sock, *, allow_fetch=False, read_timeout=5.0, write_timeout=5.0):
    """Embedding selects one owner and grants candidate effects; default is read-only.

    On successful attachment this function owns sock. Detach signals cancellation,
    but embedding must still await owner.close() and check cleanupComplete before
    destroying its Source/Inbox/Store. This descriptor is not a public network API.
    """
    await _serve_service(owner, sock, lambda: owner.attach(allow_fetch=allow_fetch),
                         protocol=PROTOCOL, operations=OPERATIONS,
                         read_timeout=read_timeout, write_timeout=write_timeout)
