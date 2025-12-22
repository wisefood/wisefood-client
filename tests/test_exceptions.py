from wisefood.exceptions import DataError, error_from_response


class StubResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    @property
    def text(self):
        return ""


def test_validation_error_includes_detail_message():
    payload = {
        "detail": [
            {"loc": ["body", "title"], "msg": "field required", "type": "value_error.missing"}
        ]
    }
    resp = StubResponse(422, payload)

    err = error_from_response(resp)

    assert isinstance(err, DataError)
    assert "body.title: field required" in str(err)
    assert err.errors == payload["detail"]
    assert err.response_body == payload


def test_enveloped_validation_error_includes_detail_message():
    payload = {
        "success": False,
        "error": {
            "title": "RequestValidationError",
            "detail": "Validation failed",
            "code": "request/unprocessable",
            "errors": [
                {
                    "type": "string_pattern_mismatch",
                    "loc": ["body", "urn"],
                    "msg": "String should match pattern '^[a-z0-9]+(?:[-_][a-z0-9]+)*$'",
                    "input": "urn:article:bad",
                    "ctx": {"pattern": "^[a-z0-9]+(?:[-_][a-z0-9]+)*$"},
                }
            ],
        },
        "help": "http://example/api/v1/articles",
    }
    resp = StubResponse(422, payload)

    err = error_from_response(resp)

    assert isinstance(err, DataError)
    assert "Validation failed: body.urn: String should match pattern" in str(err)
    assert err.errors == payload["error"]["errors"]
