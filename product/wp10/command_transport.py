"""Dedicated trusted, preconnected command descriptor; never a public listener."""
from .commands import EventCommandHost, PROTOCOL, OPERATIONS
from .transport import _serve_service


async def serve_commands_connected(host: EventCommandHost, sock, *, allow_publish=False,
                                   read_timeout=5.0, write_timeout=5.0):
    """The embedding grants publication explicitly; default is read-only inquiry.

    This function owns/closes the socket after successful attachment. Retain and
    close EventCommandHost, EventHost and both stores separately in that order.
    """
    await _serve_service(host, sock, lambda: host.attach(allow_publish=allow_publish),
                         protocol=PROTOCOL, operations=OPERATIONS,
                         read_timeout=read_timeout, write_timeout=write_timeout)
