"""Turn the network off from inside the process.

WHY this exists rather than "we tested it with wifi off": a demo-safe mode that is verified by
unplugging is verified once, by a human, at the wrong hour. A demo-safe mode that refuses to
open a socket is verified on every run, by the test suite, on a machine that happens to have
working wifi. The guard is the assertion.

Loopback stays open, because the presenter's browser and `demo/verify.py` both talk to the
server over it. Everything else raises `OfflineError`, which is a `ConnectionError`: any
library that catches connection failures degrades exactly as it would with the cable pulled,
which is the behaviour we are trying to rehearse.
"""

from __future__ import annotations

import socket

_LOOPBACK_HOSTS = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})
_INET = (socket.AF_INET, socket.AF_INET6)

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_installed = False


class OfflineError(ConnectionError):
    """Raised instead of reaching the network. A ConnectionError so callers degrade normally."""


def _host_of(address) -> str | None:
    """The host out of whatever `connect` was handed, or None when it is not an IP socket."""
    if isinstance(address, (tuple, list)) and address:
        return str(address[0])
    return None


def is_local(address) -> bool:
    """True for loopback and for non-IP families (AF_UNIX is local by construction)."""
    host = _host_of(address)
    if host is None:
        return True
    host = host.strip("[]").split("%", 1)[0]        # strip brackets and an IPv6 scope id
    if host in _LOOPBACK_HOSTS or host in ("::1", "::", "0.0.0.0", ""):
        return True
    return host.startswith("127.")


def _guarded_connect(self, address, *args, **kwargs):
    if self.family in _INET and not is_local(address):
        raise OfflineError(
            f"demo.netguard: refused an outbound connection to {address!r}. "
            f"DEMO_SAFE means zero network -- if you need this call, you are not demo-safe.")
    return _real_connect(self, address, *args, **kwargs)


def _guarded_connect_ex(self, address, *args, **kwargs):
    if self.family in _INET and not is_local(address):
        return 111                                   # ECONNREFUSED: the honest kernel answer
    return _real_connect_ex(self, address, *args, **kwargs)


def install() -> None:
    """Block non-loopback connects for the rest of this process. Idempotent."""
    global _installed
    if _installed:
        return
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex
    _installed = True


def uninstall() -> None:
    """Undo `install`. Exists for tests; nothing in the demo path calls it."""
    global _installed
    socket.socket.connect = _real_connect
    socket.socket.connect_ex = _real_connect_ex
    _installed = False


def installed() -> bool:
    return _installed
