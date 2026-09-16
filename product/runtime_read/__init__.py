"""Local owner-side observation adapter; no transport or write authority."""
from .observer import StoreObserver, ObservationError
__all__ = ['StoreObserver', 'ObservationError']
