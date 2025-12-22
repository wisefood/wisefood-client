import sys
import types
from pathlib import Path

import pytest

# Allow tests to import the package from src without installation
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class StubResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


class StubSession:
    def __init__(self):
        self.post_calls = []
        self.request_calls = []
        self.post_response = StubResponse()
        self.request_response = StubResponse()

    def post(self, url, json=None, verify=None, timeout=None):
        self.post_calls.append(
            {"url": url, "json": json, "verify": verify, "timeout": timeout}
        )
        return self.post_response

    def request(self, method, url, headers=None, params=None, verify=None, timeout=None, **kwargs):
        self.request_calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "params": params or {},
                "verify": verify,
                "timeout": timeout,
                "kwargs": kwargs,
            }
        )
        return self.request_response


class DummyClient:
    """
    Lightweight stand-in for the Wisefood Client used by entity tests.
    """

    def __init__(self):
        self.calls = []
        self.responses = {}

    def queue_response(self, method, endpoint, response):
        self.responses[(method, endpoint)] = response

    def _take(self, method, endpoint):
        key = (method, endpoint)
        if key not in self.responses:
            raise AssertionError(f"No queued response for {method} {endpoint}")
        return self.responses[key]

    def get(self, endpoint, **kwargs):
        self.calls.append(("get", endpoint, kwargs))
        return self._take("get", endpoint)

    def post(self, endpoint, json=None, **kwargs):
        self.calls.append(("post", endpoint, json, kwargs))
        return self._take("post", endpoint)

    def patch(self, endpoint, json=None, **kwargs):
        self.calls.append(("patch", endpoint, json, kwargs))
        return self._take("patch", endpoint)

    def delete(self, endpoint, **kwargs):
        self.calls.append(("delete", endpoint, kwargs))
        # delete endpoints usually return empty responses; supply stub if not provided
        if ("delete", endpoint) in self.responses:
            return self._take("delete", endpoint)
        return StubResponse(status_code=204, json_data={})


@pytest.fixture
def dummy_client():
    return DummyClient()


@pytest.fixture
def stub_session():
    return StubSession()


@pytest.fixture
def frozen_time(monkeypatch):
    """
    Fix time.time() used by wisefood.client at a deterministic value.
    """
    current = 1_000.0
    monkeypatch.setattr("wisefood.client.time.time", lambda: current)
    return current
