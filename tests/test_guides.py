from wisefood.entities.guides import Guide, GuideGuidelinesProxy, Guideline

from conftest import DummyClient, StubResponse


GUIDE_URN = "urn:guide:mediterranean_guide"
GUIDELINE_ID = "123e4567-e89b-12d3-a456-426614174999"


def test_guide_get_and_create_use_normalized_urns(dummy_client: DummyClient):
    dummy_client.queue_response(
        "get",
        "guides/mediterranean_guide",
        StubResponse(
            200,
            {"result": {"urn": GUIDE_URN, "title": "Mediterranean Guide"}},
        ),
    )
    fetched = Guide.get(dummy_client, "mediterranean_guide")
    assert fetched.urn == GUIDE_URN
    assert fetched.title == "Mediterranean Guide"

    dummy_client.queue_response(
        "post",
        "guides",
        StubResponse(
            200,
            {"result": {"urn": GUIDE_URN, "title": "Mediterranean Guide"}},
        ),
    )
    created = Guide.create(dummy_client, urn="mediterranean_guide", title="Mediterranean Guide")
    assert created.urn == GUIDE_URN

    method, endpoint, body, _kwargs = dummy_client.calls[-1]
    assert method == "post"
    assert endpoint == "guides"
    assert body["urn"] == "mediterranean_guide"


def test_guide_embedded_relationship_aliases_are_exposed(dummy_client: DummyClient):
    guide = Guide(
        client=dummy_client,
        data={
            "urn": GUIDE_URN,
            "title": "Mediterranean Guide",
            "artifacts": [{"id": "artifact-1"}],
            "guidelines": [GUIDELINE_ID],
        },
        sync=False,
    )

    assert guide.artifact_records == [{"id": "artifact-1"}]
    assert guide.guideline_ids == [GUIDELINE_ID]


def test_guideline_get_uses_uuid_endpoint(dummy_client: DummyClient):
    dummy_client.queue_response(
        "get",
        f"guidelines/{GUIDELINE_ID}",
        StubResponse(
            200,
            {
                "result": {
                    "id": GUIDELINE_ID,
                    "guide_urn": GUIDE_URN,
                    "rule_text": "Eat vegetables daily",
                    "sequence_no": 1,
                    "action_type": "encourage",
                }
            },
        ),
    )

    guideline = Guideline.get(dummy_client, GUIDELINE_ID)

    assert guideline.id == GUIDELINE_ID
    assert guideline.guide_urn == GUIDE_URN
    assert guideline.rule_text == "Eat vegetables daily"


def test_guide_guidelines_proxy_is_bound(dummy_client: DummyClient):
    guide = Guide(
        client=dummy_client,
        data={"urn": GUIDE_URN, "title": "Mediterranean Guide"},
        sync=False,
    )

    dummy_client.queue_response(
        "get",
        "guidelines",
        StubResponse(200, {"result": [{"id": GUIDELINE_ID}]}),
    )

    proxy = guide.guidelines
    guidelines = proxy[:1]

    assert isinstance(proxy, GuideGuidelinesProxy)
    assert isinstance(guidelines[0], Guideline)
    assert guidelines[0].id == GUIDELINE_ID

    method, endpoint, kwargs = dummy_client.calls[-1]
    assert method == "get"
    assert endpoint == "guidelines"
    assert kwargs == {
        "guide_urn": GUIDE_URN,
        "limit": 1,
        "offset": 0,
    }


def test_guide_guidelines_create_injects_guide_urn(dummy_client: DummyClient):
    guide = Guide(
        client=dummy_client,
        data={"urn": GUIDE_URN, "title": "Mediterranean Guide"},
        sync=False,
    )

    dummy_client.queue_response(
        "post",
        "guidelines",
        StubResponse(
            200,
            {
                "result": {
                    "id": GUIDELINE_ID,
                    "guide_urn": GUIDE_URN,
                    "rule_text": "Eat vegetables daily",
                    "sequence_no": 1,
                    "action_type": "encourage",
                }
            },
        ),
    )

    created = guide.guidelines.create(
        rule_text="Eat vegetables daily",
        sequence_no=1,
        action_type="encourage",
    )

    method, endpoint, body, _kwargs = dummy_client.calls[-1]
    assert method == "post"
    assert endpoint == "guidelines"
    assert body["guide_urn"] == GUIDE_URN
    assert created.guide_urn == GUIDE_URN
