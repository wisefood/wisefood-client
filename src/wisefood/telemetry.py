"""Usage telemetry for the WiseFood Python client.

Why an SDK sends telemetry at all: the platform's analytics answer "what are
people doing with WiseFood", and a meaningful share of that is project partners
and evaluation notebooks driving the API directly rather than through the web
app. Without this they are invisible, and every usage report silently means
"usage through the browser".

Three rules, all of them about not being in the way:

* nothing blocks the caller — events go on a queue, a daemon thread posts them;
* nothing raises into the caller — a broken ingest is a dropped batch;
* it is trivially switchable — ``WISEFOOD_TELEMETRY=0`` or
  ``Client(..., telemetry=False)``, and it is off automatically when the
  gateway does not accept it.

What is sent: which SDK method was called, whether it succeeded, and how long
it took. Never arguments, never results, never anything a caller passed in.
"""

from __future__ import annotations

import atexit
import logging
import os
import queue
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

QUEUE_MAX = 1000
BATCH_MAX = 50
FLUSH_INTERVAL = 5.0
HTTP_TIMEOUT = 5.0
SHUTDOWN_TIMEOUT = 3.0

_STOP = object()


def telemetry_allowed() -> bool:
    """Whether the environment permits telemetry.

    Opt-out rather than opt-in, because this is a first-party client talking to
    its own platform and the events carry no caller data — but the opt-out is
    honoured everywhere, including by the constructor flag.
    """
    raw = os.getenv("WISEFOOD_TELEMETRY")
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


class Telemetry:
    """Background reporter attached to one client instance."""

    def __init__(self, client: Any, *, enabled: bool = True, app: str = "platform"):
        self._client = client
        self._app = app
        self._enabled = bool(enabled) and telemetry_allowed()
        self._queue: "queue.Queue" = queue.Queue(maxsize=QUEUE_MAX)
        self._thread: Optional[threading.Thread] = None
        self._session_id = uuid.uuid4().hex[:12]
        self.sent = 0
        self.dropped = 0
        self.failed = 0
        if self._enabled:
            self._start()

    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def session_id(self) -> str:
        """Groups everything this client instance did, like the browser's."""
        return self._session_id

    def _start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="wisefood-telemetry", daemon=True
        )
        self._thread.start()
        atexit.register(self.close)

    def track(self, event_type: str, *, app: Optional[str] = None, **props: Any) -> None:
        """Record one event. Returns immediately; never raises."""
        if not self._enabled:
            return
        try:
            self._queue.put_nowait(
                {
                    "type": event_type,
                    "app": app or self._app,
                    "occurred_at": _now_iso(),
                    "props": {k: v for k, v in props.items() if v is not None},
                }
            )
        except queue.Full:
            self.dropped += 1
        except Exception:
            self.dropped += 1

    def flush(self, timeout: float = SHUTDOWN_TIMEOUT) -> None:
        """Send what is queued now and keep running.

        Distinct from :meth:`close`: a script that flushes mid-run expects to
        carry on recording afterwards, and an earlier version quietly stopped
        the reporter, so everything after the flush was silently discarded.
        """
        if not self._thread or not self._enabled:
            return
        deadline = time.monotonic() + timeout
        while not self._queue.empty() and time.monotonic() < deadline:
            time.sleep(0.05)

    def close(self) -> None:
        """Flush what is queued, briefly, then stop. Safe to call twice."""
        if not self._thread:
            return
        self._enabled = False
        try:
            self._queue.put_nowait(_STOP)
        except queue.Full:
            pass
        self._thread.join(timeout=SHUTDOWN_TIMEOUT)
        self._thread = None

    # ------------------------------------------------------------------
    def _run(self) -> None:
        while True:
            batch = self._collect()
            if batch is None:
                return
            if batch:
                self._post(batch)

    def _collect(self) -> Optional[List[Dict[str, Any]]]:
        batch: List[Dict[str, Any]] = []
        try:
            first = self._queue.get(timeout=FLUSH_INTERVAL)
        except queue.Empty:
            return batch
        if first is _STOP:
            return self._drain()
        batch.append(first)
        deadline = time.monotonic() + FLUSH_INTERVAL
        while len(batch) < BATCH_MAX:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                item = self._queue.get(timeout=remaining)
            except queue.Empty:
                break
            if item is _STOP:
                self._post(batch)
                return self._drain()
            batch.append(item)
        return batch

    def _drain(self) -> None:
        remaining: List[Dict[str, Any]] = []
        while not self._queue.empty() and len(remaining) < BATCH_MAX:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is not _STOP:
                remaining.append(item)
        if remaining:
            self._post(remaining)
        return None

    def _post(self, batch: List[Dict[str, Any]]) -> None:
        if not batch:
            return
        try:
            response = self._client.request(
                "POST",
                "analytics/events",
                json={"events": batch},
                timeout=HTTP_TIMEOUT,
                headers={"X-Client-Session": self._session_id},
            )
            status = getattr(response, "status_code", 0)
            if 200 <= status < 300:
                self.sent += len(batch)
                return
            self.failed += len(batch)
            # A gateway that refuses telemetry will keep refusing it. Switching
            # off beats retrying forever from a notebook nobody is watching.
            if status in (401, 403, 404, 405):
                logger.debug("wisefood telemetry disabled (HTTP %s)", status)
                self._enabled = False
        except Exception as exc:
            self.failed += len(batch)
            logger.debug("wisefood telemetry post failed: %s", exc)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class _Null:
    """Stand-in when telemetry is off, so call sites need no guard."""

    enabled = False
    session_id = ""
    sent = dropped = failed = 0

    def track(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def flush(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def close(self) -> None:
        return None


NULL_TELEMETRY = _Null()
