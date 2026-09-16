# Primary references checked 2026-09-06

- Python socket docs: https://docs.python.org/3/library/socket.html — per-operation timeouts do not imply preemption of arbitrary synchronous work.
- Python selectors docs: https://docs.python.org/3/library/selectors.html — readiness multiplexing; reused existing selector owner architecture.
- Linux unix(7): https://man7.org/linux/man-pages/man7/unix.7.html — SO_PEERCRED and pathname socket permissions. Linux local credentials are not public network identity.

No third-party code copied. Existing project modules are reused under this repository's license.
