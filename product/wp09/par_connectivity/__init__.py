"""Local connectivity candidate; all outside-world capabilities are injected."""
from .model import (Attempt, Candidate, ConnectivityError, ConnectResult, DialTarget,
                    Endpoint, PeerProof, Policy, Resolution, RouteGrant)
from .policy import authorize_addresses, parse_endpoint, select_candidates
from .controller import Connector
from .tcp import NumericTcpDialer, SocketConnection
