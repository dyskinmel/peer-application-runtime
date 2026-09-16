"""Separately selected capability using unchanged private bounded framing."""
from product.wp10.transport import _serve_service
from .owner import PROTOCOL, OPERATIONS

async def serve_application_connected(owner, sock, *, allow_apply=False,
                                      read_timeout=5.0, write_timeout=5.0):
    await _serve_service(owner, sock, lambda: owner.attach(allow_apply=allow_apply),
                         protocol=PROTOCOL, operations=OPERATIONS,
                         read_timeout=read_timeout, write_timeout=write_timeout)
