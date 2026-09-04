"""Recording activity and feedback from the Python client.

Two small proxies hung off :class:`Client`:

    client.analytics.track("feature.used", feature="bulk-import")
    client.feedback.submit(target_type="article", target_id=urn, rating="up")

Telemetry is queued and sent in the background; feedback is sent immediately,
because somebody deliberately gave it and losing it to a process exiting would
be worse than the wait.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: Event types the gateway accepts from a client. Anything else is refused with
#: a 422 — the server keeps the list so a client cannot invent unbounded types.
CLIENT_EVENT_TYPES = frozenset(
    {
        "session.start",
        "page.view",
        "feature.used",
        "recipe.search",
        "recipe.autocomplete",
        "recipe.result_click",
        "recipe.view",
        "recipe.compare",
        "qa.ask",
        "qa.stream_abandoned",
        "qa.citation_opened",
        "chat.message",
        "chat.plan_generated",
        "chat.plan_saved",
        "chat.tool_invoked",
        "library.save",
        "library.remove",
        "favorite.add",
        "favorite.remove",
        "catalog.view",
        "console.view",
    }
)


class AnalyticsProxy:
    """``client.analytics`` — record what this script is doing."""

    def __init__(self, client: Any):
        self._client = client

    def track(
        self, event_type: str = "feature.used", *, app: str = "platform", **props: Any
    ) -> None:
        """Record one event. Never raises, never blocks.

        Unknown event types are dropped here rather than sent, so a typo shows
        up as nothing recorded instead of a 422 in the middle of a notebook.

        :param app: which surface the event belongs to — catalog, foodscholar,
            recipewrangler, foodchat or platform. Without it every SDK event
            lands under `platform` and per-product reports undercount.
        """
        if event_type not in CLIENT_EVENT_TYPES:
            logger.debug("wisefood: unknown telemetry event type %r, ignored", event_type)
            return
        self._client.telemetry.track(event_type, app=app, **props)

    def flush(self) -> None:
        """Send what is queued now and keep recording."""
        self._client.telemetry.flush()

    def close(self) -> None:
        """Send what is queued and stop recording. Called automatically at exit."""
        self._client.telemetry.close()

    @property
    def session_id(self) -> str:
        """This client's session id, as sent on every request."""
        return self._client.telemetry.session_id

    @property
    def stats(self) -> Dict[str, Any]:
        telemetry = self._client.telemetry
        return {
            "enabled": telemetry.enabled,
            "session_id": telemetry.session_id,
            "sent": telemetry.sent,
            "dropped": telemetry.dropped,
            "failed": telemetry.failed,
        }


class FeedbackProxy:
    """``client.feedback`` — tell the platform something was good or bad.

    The same inbox the web app's feedback lands in, so an evaluation run's
    judgements sit next to the users' own rather than in a spreadsheet.
    """

    def __init__(self, client: Any):
        self._client = client

    def submit(
        self,
        *,
        target_type: str = "platform",
        target_id: Optional[str] = None,
        rating: Optional[str] = None,
        score: Optional[float] = None,
        comment: Optional[str] = None,
        reason: Optional[str] = None,
        app: str = "platform",
        rating_kind: str = "thumbs",
    ) -> Dict[str, Any]:
        """Submit feedback. Raises on failure, unlike telemetry.

        :param target_type: qa_answer, chat_message, recipe, guide, article,
            textbook or platform
        :param target_id: what is being rated — an id or a urn
        :param rating: a word the surface uses, e.g. ``up``/``down``
        :param score: a number where there is a scale
        """
        payload: Dict[str, Any] = {
            "target_type": target_type,
            "rating_kind": rating_kind,
            "app": app,
        }
        if target_id is not None:
            payload["target_id"] = str(target_id)
        if rating is not None:
            payload["rating_value"] = str(rating)
        if score is not None:
            payload["rating_value_num"] = float(score)
        if comment:
            payload["comment"] = comment
        if reason:
            payload["reason"] = reason

        response = self._client.request("POST", "analytics/feedback", json=payload)
        try:
            body = response.json()
            return body.get("result", body) if isinstance(body, dict) else {}
        except Exception:
            return {}
