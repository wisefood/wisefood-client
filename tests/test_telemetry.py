"""SDK usage telemetry.

The SDK reports because a meaningful share of platform usage is partners and
evaluation notebooks driving the API directly. Without it every usage report
silently means "usage through the browser".

What these cover is the promise that makes it acceptable to ship at all: it
never blocks, never raises, never sends anything the caller passed in, and
switches off the moment anyone asks it to.
"""
import os
import queue
import time
import unittest
from unittest import mock

from wisefood.analytics import CLIENT_EVENT_TYPES, AnalyticsProxy, FeedbackProxy
from wisefood.telemetry import NULL_TELEMETRY, Telemetry, telemetry_allowed


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"result": {"accepted": 1}}

    def json(self):
        return self._payload


class FakeClient:
    """Records what would have gone over the wire."""

    def __init__(self, response=None, raises=None):
        self.calls = []
        self._response = response or FakeResponse()
        self._raises = raises

    def request(self, method, endpoint, **kwargs):
        self.calls.append((method, endpoint, kwargs))
        if self._raises:
            raise self._raises
        return self._response


class OptOutTests(unittest.TestCase):
    def test_on_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(telemetry_allowed())

    def test_env_switches_it_off(self):
        for value in ("0", "false", "no", "off", "FALSE"):
            with mock.patch.dict(os.environ, {"WISEFOOD_TELEMETRY": value}):
                self.assertFalse(telemetry_allowed(), value)

    def test_constructor_flag_wins_over_the_environment(self):
        with mock.patch.dict(os.environ, {"WISEFOOD_TELEMETRY": "1"}):
            reporter = Telemetry(FakeClient(), enabled=False)
            self.assertFalse(reporter.enabled)

    def test_a_disabled_reporter_starts_no_thread_and_records_nothing(self):
        reporter = Telemetry(FakeClient(), enabled=False)
        reporter.track("feature.used", feature="x")
        self.assertIsNone(reporter._thread)
        self.assertTrue(reporter._queue.empty())


class ServiceAccountTests(unittest.TestCase):
    """A service embedding the client is the platform talking to itself.

    FoodScholar and FoodChat both build a `Client` to read the catalog. Left on,
    their calls would be recorded as user activity — double-counting against the
    services' own reporting and filing machine traffic under a product nobody
    was using. Client credentials mean machine-to-machine, so it stays off.
    """

    def _client(self, credentials, **kwargs):
        import wisefood.api_client as api_client

        api_client.Client.authenticate = lambda self: None
        return api_client.Client(
            "http://gateway.invalid", credentials, api_prefix="api/v1", **kwargs
        )

    def test_client_credentials_never_report(self):
        from wisefood.api_client import Credentials

        client = self._client(Credentials(client_id="svc", client_secret="s"))
        self.assertFalse(client.telemetry.enabled)

    def test_user_credentials_do_report(self):
        from wisefood.api_client import Credentials

        client = self._client(Credentials(username="someone", password="p"))
        self.assertTrue(client.telemetry.enabled)
        client.telemetry.close()

    def test_asking_for_it_explicitly_does_not_override_the_service_rule(self):
        from wisefood.api_client import Credentials

        client = self._client(
            Credentials(client_id="svc", client_secret="s"), telemetry=True
        )
        self.assertFalse(client.telemetry.enabled)

    def test_no_credentials_still_reports(self):
        """A notebook against a dev gateway with auth stubbed out."""
        client = self._client(None)
        self.assertTrue(client.telemetry.enabled)
        client.telemetry.close()


class DeliveryTests(unittest.TestCase):
    def _drain(self, reporter, client, timeout=3.0):
        deadline = time.monotonic() + timeout
        while reporter._queue.qsize() and time.monotonic() < deadline:
            time.sleep(0.02)
        reporter.close()
        return client.calls

    def test_events_reach_the_ingest_endpoint_in_one_batch(self):
        client = FakeClient()
        reporter = Telemetry(client, enabled=True)
        reporter.track("feature.used", feature="a")
        reporter.track("catalog.view", urn="urn:article:x")
        calls = self._drain(reporter, client)

        self.assertEqual(len(calls), 1, "should batch, not send one request each")
        method, endpoint, kwargs = calls[0]
        self.assertEqual((method, endpoint), ("POST", "analytics/events"))
        events = kwargs["json"]["events"]
        self.assertEqual([e["type"] for e in events], ["feature.used", "catalog.view"])
        self.assertEqual(reporter.sent, 2)

    def test_the_session_id_travels_with_the_batch(self):
        client = FakeClient()
        reporter = Telemetry(client, enabled=True)
        reporter.track("feature.used")
        calls = self._drain(reporter, client)
        self.assertEqual(
            calls[0][2]["headers"]["X-Client-Session"], reporter.session_id
        )

    def test_per_event_app_overrides_the_default(self):
        client = FakeClient()
        reporter = Telemetry(client, enabled=True, app="platform")
        reporter.track("catalog.view", app="catalog")
        calls = self._drain(reporter, client)
        self.assertEqual(calls[0][2]["json"]["events"][0]["app"], "catalog")

    def test_a_refusing_gateway_switches_it_off_rather_than_retrying(self):
        """An old deployment has no ingest endpoint; retrying it forever from a
        notebook nobody is watching is the wrong answer."""
        client = FakeClient(response=FakeResponse(status_code=404))
        reporter = Telemetry(client, enabled=True)
        reporter.track("feature.used")
        self._drain(reporter, client)
        self.assertFalse(reporter.enabled)
        self.assertEqual(reporter.failed, 1)

    def test_a_raising_transport_never_reaches_the_caller(self):
        client = FakeClient(raises=RuntimeError("network is down"))
        reporter = Telemetry(client, enabled=True)
        reporter.track("feature.used")   # must not raise
        self._drain(reporter, client)
        self.assertEqual(reporter.failed, 1)

    def test_a_full_queue_drops_and_counts(self):
        reporter = Telemetry(FakeClient(), enabled=False)
        reporter._enabled = True         # no worker, so nothing is consumed
        for _ in range(reporter._queue.maxsize + 25):
            reporter.track("feature.used")
        self.assertEqual(reporter.dropped, 25)

    def test_flush_keeps_recording_but_close_does_not(self):
        """An earlier version stopped the reporter on flush, so everything a
        script did after flushing was silently discarded."""
        client = FakeClient()
        reporter = Telemetry(client, enabled=True)
        reporter.track("feature.used")
        reporter.flush()
        self.assertTrue(reporter.enabled)
        reporter.track("catalog.view")
        reporter.close()
        self.assertFalse(reporter.enabled)
        sent = [e["type"] for call in client.calls for e in call[2]["json"]["events"]]
        self.assertIn("catalog.view", sent)


class ProxyTests(unittest.TestCase):
    def test_unknown_event_types_never_leave_the_process(self):
        """A typo should be nothing recorded, not a 422 mid-notebook."""
        client = FakeClient()
        client.telemetry = mock.Mock()
        AnalyticsProxy(client).track("totally.made.up", x=1)
        client.telemetry.track.assert_not_called()

    def test_known_event_types_are_forwarded(self):
        client = FakeClient()
        client.telemetry = mock.Mock()
        AnalyticsProxy(client).track("feature.used", app="catalog", feature="import")
        client.telemetry.track.assert_called_once_with(
            "feature.used", app="catalog", feature="import"
        )

    def test_every_allowlisted_type_is_accepted(self):
        client = FakeClient()
        client.telemetry = mock.Mock()
        proxy = AnalyticsProxy(client)
        for event_type in CLIENT_EVENT_TYPES:
            proxy.track(event_type)
        self.assertEqual(client.telemetry.track.call_count, len(CLIENT_EVENT_TYPES))

    def test_feedback_is_sent_immediately_and_returns_the_receipt(self):
        """Unlike telemetry: somebody deliberately gave this, so losing it to a
        process exiting would be worse than the wait."""
        client = FakeClient(response=FakeResponse(payload={"result": {"recorded": True}}))
        receipt = FeedbackProxy(client).submit(
            target_type="article", target_id="urn:article:x", rating="up",
            comment="worked", app="catalog"
        )
        self.assertEqual(receipt, {"recorded": True})
        method, endpoint, kwargs = client.calls[0]
        self.assertEqual((method, endpoint), ("POST", "analytics/feedback"))
        self.assertEqual(kwargs["json"]["target_id"], "urn:article:x")
        self.assertEqual(kwargs["json"]["rating_value"], "up")

    def test_feedback_omits_what_was_not_given(self):
        client = FakeClient()
        FeedbackProxy(client).submit(target_type="platform", score=4.0)
        payload = client.calls[0][2]["json"]
        self.assertNotIn("comment", payload)
        self.assertNotIn("rating_value", payload)
        self.assertEqual(payload["rating_value_num"], 4.0)

    def test_the_null_reporter_satisfies_the_same_surface(self):
        """So call sites never need to guard on whether telemetry is on."""
        NULL_TELEMETRY.track("feature.used", app="catalog")
        NULL_TELEMETRY.flush()
        NULL_TELEMETRY.close()
        self.assertFalse(NULL_TELEMETRY.enabled)


if __name__ == "__main__":
    unittest.main()
