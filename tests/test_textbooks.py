from wisefood.entities.textbooks import (
    BoundTextbookPassagesProxy,
    Textbook,
    TextbookPassage,
)

from conftest import DummyClient, StubResponse


TEXTBOOK_URN = "urn:textbook:nutrition_basics"
TEXTBOOK_SLUG = "nutrition_basics"
PASSAGE_ID = "323e4567-e89b-12d3-a456-426614174999"
SECOND_PASSAGE_ID = "423e4567-e89b-12d3-a456-426614174999"
ARTIFACT_ID = "523e4567-e89b-12d3-a456-426614174999"


def test_textbook_get_and_create_use_normalized_urns(dummy_client: DummyClient):
    dummy_client.queue_response(
        "get",
        f"textbooks/{TEXTBOOK_SLUG}",
        StubResponse(
            200,
            {"result": {"urn": TEXTBOOK_URN, "title": "Nutrition Basics"}},
        ),
    )
    fetched = Textbook.get(dummy_client, TEXTBOOK_SLUG)
    assert fetched.urn == TEXTBOOK_URN
    assert fetched.title == "Nutrition Basics"

    dummy_client.queue_response(
        "post",
        "textbooks",
        StubResponse(
            200,
            {"result": {"urn": TEXTBOOK_URN, "title": "Nutrition Basics"}},
        ),
    )
    created = Textbook.create(dummy_client, urn=TEXTBOOK_SLUG, title="Nutrition Basics")
    assert created.urn == TEXTBOOK_URN

    method, endpoint, body, _kwargs = dummy_client.calls[-1]
    assert method == "post"
    assert endpoint == "textbooks"
    assert body["urn"] == TEXTBOOK_SLUG


def test_textbook_embedded_artifact_aliases_are_exposed(dummy_client: DummyClient):
    textbook = Textbook(
        client=dummy_client,
        data={
            "urn": TEXTBOOK_URN,
            "title": "Nutrition Basics",
            "artifacts": [{"id": ARTIFACT_ID, "title": "Nutrition Basics PDF"}],
        },
        sync=False,
    )

    assert textbook.artifact_records == [{"id": ARTIFACT_ID, "title": "Nutrition Basics PDF"}]
    assert textbook.artifact_record == {"id": ARTIFACT_ID, "title": "Nutrition Basics PDF"}


def test_textbook_passage_get_uses_uuid_endpoint(dummy_client: DummyClient):
    dummy_client.queue_response(
        "get",
        f"textbook-passages/{PASSAGE_ID}",
        StubResponse(
            200,
            {
                "result": {
                    "id": PASSAGE_ID,
                    "textbook_urn": TEXTBOOK_URN,
                    "artifact_id": ARTIFACT_ID,
                    "page_no": 12,
                    "sequence_no": 1,
                    "text": "Micronutrients support metabolism.",
                    "char_start": 0,
                    "char_end": 35,
                }
            },
        ),
    )

    passage = TextbookPassage.get(dummy_client, PASSAGE_ID)

    assert passage.id == PASSAGE_ID
    assert passage.textbook_urn == TEXTBOOK_URN
    assert passage.text == "Micronutrients support metabolism."


def test_textbook_passages_proxy_is_bound(dummy_client: DummyClient):
    textbook = Textbook(
        client=dummy_client,
        data={"urn": TEXTBOOK_URN, "title": "Nutrition Basics"},
        sync=False,
    )

    dummy_client.queue_response(
        "get",
        f"textbook-passages/by-textbook/{TEXTBOOK_SLUG}",
        StubResponse(200, {"result": [{"id": PASSAGE_ID}]}),
    )

    proxy = textbook.passages
    passages = proxy[:1]

    assert isinstance(proxy, BoundTextbookPassagesProxy)
    assert isinstance(passages[0], TextbookPassage)
    assert passages[0].id == PASSAGE_ID

    method, endpoint, kwargs = dummy_client.calls[-1]
    assert method == "get"
    assert endpoint == f"textbook-passages/by-textbook/{TEXTBOOK_SLUG}"
    assert kwargs == {
        "limit": 1,
        "offset": 0,
    }


def test_textbook_passages_create_injects_textbook_urn(dummy_client: DummyClient):
    textbook = Textbook(
        client=dummy_client,
        data={"urn": TEXTBOOK_URN, "title": "Nutrition Basics"},
        sync=False,
    )

    dummy_client.queue_response(
        "post",
        "textbook-passages",
        StubResponse(
            200,
            {
                "result": {
                    "id": PASSAGE_ID,
                    "textbook_urn": TEXTBOOK_URN,
                    "artifact_id": ARTIFACT_ID,
                    "page_no": 12,
                    "sequence_no": 1,
                    "text": "Micronutrients support metabolism.",
                    "char_start": 0,
                    "char_end": 35,
                }
            },
        ),
    )

    created = textbook.passages.create(
        artifact_id=ARTIFACT_ID,
        page_no=12,
        sequence_no=1,
        text="Micronutrients support metabolism.",
        char_start=0,
        char_end=35,
    )

    method, endpoint, body, _kwargs = dummy_client.calls[-1]
    assert method == "post"
    assert endpoint == "textbook-passages"
    assert body["textbook_urn"] == TEXTBOOK_URN
    assert body["artifact_id"] == ARTIFACT_ID
    assert created.textbook_urn == TEXTBOOK_URN
    assert created.page_no == 12


def test_textbook_page_lookup_returns_passages_for_page(dummy_client: DummyClient):
    textbook = Textbook(
        client=dummy_client,
        data={"urn": TEXTBOOK_URN, "title": "Nutrition Basics"},
        sync=False,
    )

    dummy_client.queue_response(
        "post",
        f"textbook-passages/by-textbook/{TEXTBOOK_SLUG}/search",
        StubResponse(
            200,
            {
                "result": {
                    "results": [
                        {
                            "id": PASSAGE_ID,
                            "textbook_urn": TEXTBOOK_URN,
                            "artifact_id": ARTIFACT_ID,
                            "page_no": 12,
                            "sequence_no": 1,
                            "text": "Micronutrients support metabolism.",
                            "char_start": 0,
                            "char_end": 35,
                        },
                        {
                            "id": SECOND_PASSAGE_ID,
                            "textbook_urn": TEXTBOOK_URN,
                            "artifact_id": ARTIFACT_ID,
                            "page_no": 12,
                            "sequence_no": 2,
                            "text": "Vitamins and minerals are essential.",
                            "char_start": 36,
                            "char_end": 75,
                        },
                    ]
                }
            },
        ),
    )

    passages = textbook.page[12]

    assert [item.id for item in passages] == [PASSAGE_ID, SECOND_PASSAGE_ID]
    assert all(isinstance(item, TextbookPassage) for item in passages)
    assert all(item.page_no == 12 for item in passages)

    method, endpoint, body, _kwargs = dummy_client.calls[-1]
    assert method == "post"
    assert endpoint == f"textbook-passages/by-textbook/{TEXTBOOK_SLUG}/search"
    assert body == {
        "limit": 10,
        "offset": 0,
        "fq": ["page_no:12"],
    }


def test_textbook_passages_bulk_replace_uses_bound_replace_endpoint(
    dummy_client: DummyClient,
):
    textbook = Textbook(
        client=dummy_client,
        data={"urn": TEXTBOOK_URN, "title": "Nutrition Basics"},
        sync=False,
    )

    dummy_client.queue_response(
        "post",
        f"textbook-passages/by-textbook/{TEXTBOOK_SLUG}/replace",
        StubResponse(
            200,
            {
                "result": [
                    {
                        "id": PASSAGE_ID,
                        "textbook_urn": TEXTBOOK_URN,
                        "artifact_id": ARTIFACT_ID,
                        "page_no": 12,
                        "sequence_no": 1,
                        "text": "Micronutrients support metabolism.",
                        "char_start": 0,
                        "char_end": 35,
                    }
                ]
            },
        ),
    )

    replaced = textbook.passages.bulk_replace(
        artifact_id=ARTIFACT_ID,
        page_count=240,
        extractor_name="pdf-parser",
        passages=[
            {
                "page_no": 12,
                "sequence_no": 1,
                "text": "Micronutrients support metabolism.",
                "char_start": 0,
                "char_end": 35,
            }
        ],
    )

    assert len(replaced) == 1
    assert isinstance(replaced[0], TextbookPassage)
    assert replaced[0].id == PASSAGE_ID

    method, endpoint, body, _kwargs = dummy_client.calls[-1]
    assert method == "post"
    assert endpoint == f"textbook-passages/by-textbook/{TEXTBOOK_SLUG}/replace"
    assert body == {
        "artifact_id": ARTIFACT_ID,
        "page_count": 240,
        "extractor_name": "pdf-parser",
        "passages": [
            {
                "page_no": 12,
                "sequence_no": 1,
                "text": "Micronutrients support metabolism.",
                "char_start": 0,
                "char_end": 35,
            }
        ],
    }
