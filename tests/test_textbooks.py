import pytest

from wisefood.entities.textbooks import (
    BoundTextbookPassagesProxy,
    Textbook,
    TextbookPassage,
    TextbookPassagesProxy,
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


def test_textbook_structure_tree_builder_uses_single_associated_artifact(
    dummy_client: DummyClient,
):
    textbook = Textbook(
        client=dummy_client,
        data={
            "urn": TEXTBOOK_URN,
            "title": "Nutrition Basics",
            "artifacts": [{"id": ARTIFACT_ID, "title": "Nutrition Basics PDF"}],
        },
        sync=False,
    )

    chapter = textbook.structure_tree.add_chapter(
        id="chapter-1",
        title="Chapter 1: Foundations",
        page_start=1,
        page_end=2,
    )
    section = chapter.add_section(
        id="section-1-1",
        title="Section 1.1",
        page_start=1,
        page_end=1,
    )

    assert chapter.artifact_id == ARTIFACT_ID
    assert section.artifact_id == ARTIFACT_ID
    assert textbook.structure_tree.chapter_1.title == "Chapter 1: Foundations"
    assert textbook.structure_tree.to_dict() == {
        "roots": [
            {
                "id": "chapter-1",
                "title": "Chapter 1: Foundations",
                "kind": "chapter",
                "artifact_id": ARTIFACT_ID,
                "page_start": 1,
                "page_end": 2,
                "children": [
                    {
                        "id": "section-1-1",
                        "title": "Section 1.1",
                        "kind": "section",
                        "artifact_id": ARTIFACT_ID,
                        "page_start": 1,
                        "page_end": 1,
                        "children": [],
                    }
                ],
            }
        ]
    }


def test_textbook_structure_tree_root_supports_nested_child_access(
    dummy_client: DummyClient,
):
    textbook = Textbook(
        client=dummy_client,
        data={
            "urn": TEXTBOOK_URN,
            "title": "Nutrition Basics",
            "artifacts": [{"id": ARTIFACT_ID, "title": "Nutrition Basics PDF"}],
        },
        sync=False,
    )

    root = textbook.structure_tree.set_root(
        id="book-root",
        title="Nutrition Basics",
        kind="book",
        page_start=1,
        page_end=2,
    )
    root.add_chapter(
        id="chapter-1",
        title="Chapter 1: Foundations",
        page_start=1,
        page_end=1,
    )

    assert textbook.structure_tree.root.chapter_1.id == "chapter-1"


def test_textbook_structure_tree_requires_single_associated_artifact(
    dummy_client: DummyClient,
):
    textbook = Textbook(
        client=dummy_client,
        data={"urn": TEXTBOOK_URN, "title": "Nutrition Basics"},
        sync=False,
    )

    with pytest.raises(ValueError, match="exactly one associated artifact"):
        textbook.structure_tree.add_chapter(
            id="chapter-1",
            title="Chapter 1: Foundations",
            page_start=1,
            page_end=1,
        )


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
        f"textbook-passages/by-textbook/{TEXTBOOK_URN}",
        StubResponse(200, {"result": [{"id": PASSAGE_ID}]}),
    )

    proxy = textbook.passages
    passages = proxy[:1]

    assert isinstance(proxy, BoundTextbookPassagesProxy)
    assert isinstance(passages[0], TextbookPassage)
    assert passages[0].id == PASSAGE_ID

    method, endpoint, kwargs = dummy_client.calls[-1]
    assert method == "get"
    assert endpoint == f"textbook-passages/by-textbook/{TEXTBOOK_URN}"
    assert kwargs == {
        "limit": 1,
        "offset": 0,
    }


def test_textbook_passages_by_textbook_accepts_slug_but_uses_full_urn_endpoint(
    dummy_client: DummyClient,
):
    dummy_client.queue_response(
        "get",
        f"textbook-passages/by-textbook/{TEXTBOOK_URN}",
        StubResponse(200, {"result": [{"id": PASSAGE_ID}]}),
    )

    proxy = TextbookPassagesProxy(dummy_client).by_textbook(TEXTBOOK_SLUG)
    passages = proxy[:1]

    assert isinstance(passages[0], TextbookPassage)
    assert passages[0].id == PASSAGE_ID

    method, endpoint, kwargs = dummy_client.calls[-1]
    assert method == "get"
    assert endpoint == f"textbook-passages/by-textbook/{TEXTBOOK_URN}"
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


def test_textbook_passages_create_uses_single_associated_artifact(
    dummy_client: DummyClient,
):
    textbook = Textbook(
        client=dummy_client,
        data={
            "urn": TEXTBOOK_URN,
            "title": "Nutrition Basics",
            "artifacts": [{"id": ARTIFACT_ID, "title": "Nutrition Basics PDF"}],
        },
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
    assert created.artifact_id == ARTIFACT_ID


def test_textbook_page_lookup_returns_passages_for_page(dummy_client: DummyClient):
    textbook = Textbook(
        client=dummy_client,
        data={"urn": TEXTBOOK_URN, "title": "Nutrition Basics"},
        sync=False,
    )

    dummy_client.queue_response(
        "post",
        f"textbook-passages/by-textbook/{TEXTBOOK_URN}/search",
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
    assert endpoint == f"textbook-passages/by-textbook/{TEXTBOOK_URN}/search"
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
        f"textbook-passages/by-textbook/{TEXTBOOK_URN}/replace",
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
    assert endpoint == f"textbook-passages/by-textbook/{TEXTBOOK_URN}/replace"
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


def test_textbook_passages_bulk_replace_uses_textbook_artifact_and_structure_helper(
    dummy_client: DummyClient,
):
    textbook = Textbook(
        client=dummy_client,
        data={
            "urn": TEXTBOOK_URN,
            "title": "Nutrition Basics",
            "artifacts": [{"id": ARTIFACT_ID, "title": "Nutrition Basics PDF"}],
        },
        sync=False,
    )

    textbook.structure_tree.add_chapter(
        id="chapter-1",
        title="Chapter 1: Foundations",
        page_start=1,
        page_end=1,
    )

    dummy_client.queue_response(
        "post",
        f"textbook-passages/by-textbook/{TEXTBOOK_URN}/replace",
        StubResponse(
            200,
            {
                "result": [
                    {
                        "id": PASSAGE_ID,
                        "textbook_urn": TEXTBOOK_URN,
                        "artifact_id": ARTIFACT_ID,
                        "page_no": 1,
                        "sequence_no": 1,
                        "text": "Micronutrients support metabolism.",
                        "char_start": 0,
                        "char_end": 35,
                    }
                ]
            },
        ),
    )

    textbook.passages.bulk_replace(
        page_count=1,
        structure_tree=textbook.structure_tree,
        passages=[
            {
                "page_no": 1,
                "sequence_no": 1,
                "text": "Micronutrients support metabolism.",
                "char_start": 0,
                "char_end": 35,
            }
        ],
    )

    method, endpoint, body, _kwargs = dummy_client.calls[-1]
    assert method == "post"
    assert endpoint == f"textbook-passages/by-textbook/{TEXTBOOK_URN}/replace"
    assert body == {
        "artifact_id": ARTIFACT_ID,
        "page_count": 1,
        "structure_tree": {
            "roots": [
                {
                    "id": "chapter-1",
                    "title": "Chapter 1: Foundations",
                    "kind": "chapter",
                    "artifact_id": ARTIFACT_ID,
                    "page_start": 1,
                    "page_end": 1,
                    "children": [],
                }
            ]
        },
        "passages": [
            {
                "page_no": 1,
                "sequence_no": 1,
                "text": "Micronutrients support metabolism.",
                "char_start": 0,
                "char_end": 35,
            }
        ],
    }
