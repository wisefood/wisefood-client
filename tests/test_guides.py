from wisefood.entities.guides import Guide, GuideGuidelinesProxy, Guideline

from conftest import DummyClient, StubResponse


GUIDE_URN = "urn:guide:mediterranean_guide"
GUIDELINE_ID = "123e4567-e89b-12d3-a456-426614174999"
SECOND_GUIDELINE_ID = "223e4567-e89b-12d3-a456-426614174999"


def test_guide_get_and_create_use_normalized_urns(dummy_client: DummyClient):
    dummy_client.queue_response(
        "get",
        "guides/mediterranean_guide",
        StubResponse(
            200,
            {
                "result": {
                    "urn": GUIDE_URN,
                    "title": "Mediterranean Guide",
                    "page_count": 32,
                }
            },
        ),
    )
    fetched = Guide.get(dummy_client, "mediterranean_guide")
    assert fetched.urn == GUIDE_URN
    assert fetched.title == "Mediterranean Guide"
    assert fetched.page_count == 32

    dummy_client.queue_response(
        "post",
        "guides",
        StubResponse(
            200,
            {
                "result": {
                    "urn": GUIDE_URN,
                    "title": "Mediterranean Guide",
                    "page_count": 32,
                }
            },
        ),
    )
    created = Guide.create(
        dummy_client,
        urn="mediterranean_guide",
        title="Mediterranean Guide",
        page_count=32,
    )
    assert created.urn == GUIDE_URN
    assert created.page_count == 32

    method, endpoint, body, _kwargs = dummy_client.calls[-1]
    assert method == "post"
    assert endpoint == "guides"
    assert body["urn"] == "mediterranean_guide"
    assert body["page_count"] == 32


def test_guide_save_only_dirty_sends_page_count(dummy_client: DummyClient):
    guide = Guide(
        client=dummy_client,
        data={
            "urn": GUIDE_URN,
            "title": "Mediterranean Guide",
            "page_count": 24,
        },
        sync=False,
    )

    guide.page_count = 32

    dummy_client.queue_response(
        "patch",
        "guides/mediterranean_guide",
        StubResponse(
            200,
            {
                "result": {
                    "urn": GUIDE_URN,
                    "title": "Mediterranean Guide",
                    "page_count": 32,
                }
            },
        ),
    )

    guide.save(only_dirty=True)

    method, endpoint, body, _kwargs = dummy_client.calls[-1]
    assert method == "patch"
    assert endpoint == "guides/mediterranean_guide"
    assert body == {"page_count": 32}
    assert guide.page_count == 32


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
        f"guidelines/by-guide/{GUIDE_URN}",
        StubResponse(200, {"result": [{"id": GUIDELINE_ID}]}),
    )

    proxy = guide.guidelines
    guidelines = proxy[:1]

    assert isinstance(proxy, GuideGuidelinesProxy)
    assert isinstance(guidelines[0], Guideline)
    assert guidelines[0].id == GUIDELINE_ID

    method, endpoint, kwargs = dummy_client.calls[-1]
    assert method == "get"
    assert endpoint == f"guidelines/by-guide/{GUIDE_URN}"
    assert kwargs == {
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
                    "page_no": 3,
                    "action_type": "encourage",
                }
            },
        ),
    )

    created = guide.guidelines.create(
        rule_text="Eat vegetables daily",
        sequence_no=1,
        page_no=3,
        action_type="encourage",
    )

    method, endpoint, body, _kwargs = dummy_client.calls[-1]
    assert method == "post"
    assert endpoint == "guidelines"
    assert body["guide_urn"] == GUIDE_URN
    assert body["page_no"] == 3
    assert created.guide_urn == GUIDE_URN
    assert created.page_no == 3


def test_guide_page_lookup_returns_guidelines_for_page(dummy_client: DummyClient):
    guide = Guide(
        client=dummy_client,
        data={"urn": GUIDE_URN, "title": "Mediterranean Guide"},
        sync=False,
    )

    dummy_client.queue_response(
        "post",
        "guidelines/search",
        StubResponse(
            200,
            {
                "result": {
                    "results": [
                        {
                            "id": GUIDELINE_ID,
                            "guide_urn": GUIDE_URN,
                            "rule_text": "Eat vegetables daily",
                            "page_no": 12,
                        },
                        {
                            "id": SECOND_GUIDELINE_ID,
                            "guide_urn": GUIDE_URN,
                            "rule_text": "Choose olive oil often",
                            "page_no": 12,
                        },
                    ]
                }
            },
        ),
    )

    guidelines = guide.page[12]

    assert [item.id for item in guidelines] == [GUIDELINE_ID, SECOND_GUIDELINE_ID]
    assert all(isinstance(item, Guideline) for item in guidelines)
    assert all(item.page_no == 12 for item in guidelines)

    method, endpoint, body, _kwargs = dummy_client.calls[-1]
    assert method == "post"
    assert endpoint == "guidelines/search"
    assert body == {
        "limit": 1000,
        "offset": 0,
        "fq": [
            f'guide_urn:"{GUIDE_URN}"',
            "page_no:12",
        ]
    }


def test_guide_guidelines_search_uses_scoped_endpoint(dummy_client: DummyClient):
    guide = Guide(
        client=dummy_client,
        data={"urn": GUIDE_URN, "title": "Mediterranean Guide"},
        sync=False,
    )

    dummy_client.queue_response(
        "post",
        f"guidelines/by-guide/{GUIDE_URN}/search",
        StubResponse(
            200,
            {
                "result": {
                    "results": [
                        {
                            "id": GUIDELINE_ID,
                            "guide_urn": GUIDE_URN,
                            "rule_text": "Eat vegetables daily",
                        }
                    ]
                }
            },
        ),
    )

    results = guide.guidelines.search(
        "vegetables",
        limit=5,
        fq=["status:draft"],
    )

    assert [item.id for item in results] == [GUIDELINE_ID]
    assert all(isinstance(item, Guideline) for item in results)

    method, endpoint, body, _kwargs = dummy_client.calls[-1]
    assert method == "post"
    assert endpoint == f"guidelines/by-guide/{GUIDE_URN}/search"
    assert body == {
        "q": "vegetables",
        "limit": 5,
        "offset": 0,
        "fq": ["status:draft"],
    }
