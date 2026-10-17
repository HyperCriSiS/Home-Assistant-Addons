#!/usr/bin/env python3
"""Bounded, redacted live logs for tunnel subprocesses.

Data remains in memory, is never persisted, and is served only via HA Ingress.
"""
from collections import deque
from datetime import datetime, timezone
import io
import re
import threading

MAX_LINES = 160
MAX_CHARS = 420
PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/\-=]+"),
    re.compile(r"(?i)\b(?:access[_-]?token|api[_-]?key|password|secret|authorization|credential)\b\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)([?&](?:token|key|secret|authorization)=)[^&\s]+"),
)


def redact(line, secrets=()):
    text = str(line).replace("\r", " ").replace("\n", " ")
    for secret in secrets:
        if secret and len(secret) >= 8:
            text = text.replace(secret, "[REDACTED]")
    for pattern in PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text[:MAX_CHARS]


class TunnelLog:
    def __init__(self):
        self.lines = deque(maxlen=MAX_LINES)
        self.lock = threading.Lock()

    def add(self, message, secrets=()):
        clean = redact(message, secrets)
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        with self.lock:
            self.lines.append(stamp + "  " + clean)

    def follow(self, proc, secrets=()):
        """Drain pipes independently so tunnel processes cannot block on stderr."""
        pipe = getattr(proc, "stdout", None)
        if not isinstance(pipe, io.TextIOBase):
            return

        def reader():
            try:
                for line in pipe:
                    self.add(line, secrets)
            except (OSError, ValueError):
                self.add("Prozessprotokoll nicht mehr verfügbar")
            finally:
                try:
                    pipe.close()
                except (OSError, ValueError):
                    pass

        threading.Thread(target=reader, daemon=True, name="tunnel-log-reader").start()

    def snapshot(self):
        with self.lock:
            return {"lines": list(self.lines), "limited": True}
