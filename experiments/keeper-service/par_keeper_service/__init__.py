"""Bounded private IPC candidate. Not PAR-v1 transport or a production service."""
from .errors import ServiceError
from .protocol import (PROFILE,MAX_HELLO,MAX_REQUEST,MAX_RESPONSE,METHODS,make_hello,check_hello,make_request,check_request,make_response,check_response)
from .transport import frame,receive,send,recover_stale,socket_identity
from .server import Server
from .client import Client,RemoteProvider
