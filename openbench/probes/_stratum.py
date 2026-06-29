"""Shared Stratum v1 message model for the probes (msgspec).

Mirrors erikslund_pool/stratum.py's approach — one permissive `msgspec.Struct` plus a module-level
`Decoder` — adapted for the client side (we receive responses *and* notifications, so this carries
`result`/`error` too). The probes are standalone scripts mounted together at `/probes`, so each can
`from _stratum import ...`.
"""

from __future__ import annotations

from typing import Any

import msgspec


class StratumMessage(msgspec.Struct):
    """A decoded inbound line: a notification (method + params) or a response (id + result/error)."""

    id: Any = None
    method: str | None = None
    params: Any = msgspec.field(default_factory=list)
    result: Any = None
    error: Any = None


DECODER = msgspec.json.Decoder(StratumMessage)

encode = msgspec.json.encode  # raw JSON-encode -> bytes (for building partial frames)
decode = msgspec.json.decode  # untyped decode -> dict/list (non-Stratum JSON, e.g. bitcoind RPC)


def frame(message: dict[str, Any]) -> bytes:
    """Encode an outbound message dict as a newline-terminated JSON frame."""
    return msgspec.json.encode(message) + b"\n"
