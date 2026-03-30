import types
from pathlib import Path

from wisefood.entities.articles import Article
from wisefood.entities.artifacts import Artifact, ArtifactsProxy, ParentArtifactsProxy
from wisefood.entities.guides import Guide
from wisefood.entities.textbooks import Textbook

from conftest import DummyClient, StubResponse


ARTIFACT_ID = "123e4567-e89b-12d3-a456-426614174000"
GUIDE_URN = "urn:guide:mediterranean_guide"
TEXTBOOK_URN = "urn:textbook:nutrition_basics"


class StreamingResponse:
    def __init__(self, chunks):
        self._chunks = chunks
        self.closed = False

    def iter_content(self, chunk_size=8192):
        yield from self._chunks

    def close(self):
        self.closed = True


def test_artifact_get_uses_uuid_endpoint(dummy_client: DummyClient):
    dummy_client.queue_response(
        "get",
        f"artifacts/{ARTIFACT_ID}",
        StubResponse(
            200,
            {
                "result": {
                    "id": ARTIFACT_ID,
                    "parent_urn": "urn:article:one",
                    "title": "Supplementary PDF",
                    "description": "Attached document",
                    "type": "artifact",
                    "file_url": "https://files.example.com/a.pdf",
                    "file_type": "application/pdf",
                    "file_size": 128,
                }
            },
        ),
    )

    artifact = Artifact.get(dummy_client, ARTIFACT_ID)

    assert artifact.id == ARTIFACT_ID
    assert artifact.parent_urn == "urn:article:one"
    assert artifact.title == "Supplementary PDF"


def test_artifacts_proxy_string_lookup_supports_uuid(monkeypatch):
    proxy = ArtifactsProxy(client=None)  # type: ignore[arg-type]
    proxy._urns = [ARTIFACT_ID]

    def get_entity(self, identifier, lazy=False):
        return f"entity:{identifier}"

    monkeypatch.setattr(proxy, "_get_entity", types.MethodType(get_entity, proxy))

    assert proxy[ARTIFACT_ID] == f"entity:{ARTIFACT_ID}"
    assert proxy.slugs() == [ARTIFACT_ID]


def test_artifact_save_only_dirty_includes_file_type(dummy_client: DummyClient):
    artifact = Artifact(
        client=dummy_client,
        data={
            "id": ARTIFACT_ID,
            "parent_urn": "urn:article:one",
            "title": "Old title",
            "description": "Attached document",
            "file_url": "https://files.example.com/a.pdf",
            "file_type": "application/pdf",
            "file_size": 128,
        },
        sync=False,
    )

    artifact.title = "New title"

    dummy_client.queue_response(
        "patch",
        f"artifacts/{ARTIFACT_ID}",
        StubResponse(
            200,
            {
                "result": {
                    "id": ARTIFACT_ID,
                    "parent_urn": "urn:article:one",
                    "title": "New title",
                    "description": "Attached document",
                    "file_url": "https://files.example.com/a.pdf",
                    "file_type": "application/pdf",
                    "file_size": 128,
                }
            },
        ),
    )

    artifact.save(only_dirty=True)

    method, endpoint, json_body, _kwargs = dummy_client.calls[-1]
    assert method == "patch"
    assert endpoint == f"artifacts/{ARTIFACT_ID}"
    assert json_body == {
        "title": "New title",
        "file_type": "application/pdf",
    }


def test_artifact_download_uses_download_endpoint(dummy_client: DummyClient):
    artifact = Artifact(
        client=dummy_client,
        data={
            "id": ARTIFACT_ID,
            "parent_urn": "urn:article:one",
            "title": "Supplementary PDF",
        },
        sync=False,
    )

    dummy_client.queue_response(
        "get",
        f"artifacts/{ARTIFACT_ID}/download",
        StubResponse(200, {"result": "https://files.example.com/download"}),
    )

    resp = artifact.download()

    assert resp.json()["result"] == "https://files.example.com/download"
    assert ("get", f"artifacts/{ARTIFACT_ID}/download", {}) in dummy_client.calls


def test_artifact_download_to_writes_local_file(dummy_client: DummyClient, tmp_path: Path):
    artifact = Artifact(
        client=dummy_client,
        data={
            "id": ARTIFACT_ID,
            "parent_urn": "urn:article:one",
            "title": "Supplementary PDF",
        },
        sync=False,
    )
    response = StreamingResponse([b"abc", b"", b"def"])
    dummy_client.queue_response("get", f"artifacts/{ARTIFACT_ID}/download", response)

    destination = tmp_path / "downloads" / "artifact.pdf"
    written_path = artifact.download_to(destination)

    assert written_path == destination
    assert destination.read_bytes() == b"abcdef"
    assert response.closed is True
    assert ("get", f"artifacts/{ARTIFACT_ID}/download", {"stream": True}) in dummy_client.calls


def test_artifacts_proxy_download_to_writes_local_file(
    dummy_client: DummyClient, tmp_path: Path
):
    proxy = ArtifactsProxy(dummy_client)
    response = StreamingResponse([b"guide", b"-pdf"])
    dummy_client.queue_response("get", f"artifacts/{ARTIFACT_ID}/download", response)

    destination = tmp_path / "client-level.pdf"
    written_path = proxy.download_to(ARTIFACT_ID, destination)

    assert written_path == destination
    assert destination.read_bytes() == b"guide-pdf"
    assert response.closed is True
    assert ("get", f"artifacts/{ARTIFACT_ID}/download", {"stream": True}) in dummy_client.calls


def test_parent_artifacts_proxy_download_to_writes_local_file(
    dummy_client: DummyClient, tmp_path: Path
):
    guide = Guide(
        client=dummy_client,
        data={"urn": GUIDE_URN, "title": "Mediterranean Guide"},
        sync=False,
    )
    response = StreamingResponse([b"page-1"])
    dummy_client.queue_response("get", f"artifacts/{ARTIFACT_ID}/download", response)

    destination = tmp_path / "guide-bound.pdf"
    written_path = guide.artifacts.download_to(ARTIFACT_ID, destination)

    assert written_path == destination
    assert destination.read_bytes() == b"page-1"
    assert response.closed is True
    assert ("get", f"artifacts/{ARTIFACT_ID}/download", {"stream": True}) in dummy_client.calls


def test_parent_entity_exposes_bound_artifacts_proxy(dummy_client: DummyClient):
    article = Article(
        client=dummy_client,
        data={"urn": "urn:article:one", "title": "Example"},
        sync=False,
    )

    dummy_client.queue_response(
        "get",
        "artifacts",
        StubResponse(200, {"result": [{"id": ARTIFACT_ID}]}),
    )

    proxy = article.artifacts
    artifacts = proxy[:1]

    assert isinstance(proxy, ParentArtifactsProxy)
    assert isinstance(artifacts[0], Artifact)
    assert artifacts[0].id == ARTIFACT_ID

    method, endpoint, kwargs = dummy_client.calls[-1]
    assert method == "get"
    assert endpoint == "artifacts"
    assert kwargs == {
        "parent_urn": "urn:article:one",
        "limit": 1,
        "offset": 0,
    }


def test_parent_entity_uses_embedded_artifacts_for_proxy_slice(dummy_client: DummyClient):
    guide = Guide(
        client=dummy_client,
        data={
            "urn": GUIDE_URN,
            "title": "Mediterranean Guide",
            "artifacts": [
                {
                    "id": ARTIFACT_ID,
                    "parent_urn": GUIDE_URN,
                    "title": "Guide PDF",
                    "description": "Embedded artifact payload",
                    "type": "artifact",
                    "file_url": "https://files.example.com/guide.pdf",
                    "file_type": "application/pdf",
                    "file_size": 512,
                }
            ],
        },
        sync=False,
    )

    artifact = guide.artifacts[:1][0]

    assert isinstance(artifact, Artifact)
    assert artifact.id == ARTIFACT_ID
    assert artifact.title == "Guide PDF"
    assert dummy_client.calls == []


def test_parent_entity_uses_embedded_artifacts_for_direct_lookup(dummy_client: DummyClient):
    guide = Guide(
        client=dummy_client,
        data={
            "urn": GUIDE_URN,
            "title": "Mediterranean Guide",
            "artifacts": [
                {
                    "id": ARTIFACT_ID,
                    "title": "Guide PDF",
                    "description": "Embedded artifact payload",
                    "type": "artifact",
                    "file_url": "https://files.example.com/guide.pdf",
                    "file_type": "application/pdf",
                    "file_size": 512,
                }
            ],
        },
        sync=False,
    )

    artifact = guide.artifacts[ARTIFACT_ID]

    assert artifact.id == ARTIFACT_ID
    assert artifact.parent_urn == GUIDE_URN
    assert artifact.title == "Guide PDF"
    assert dummy_client.calls == []


def test_parent_entity_direct_artifact_lookup_validates_parent(dummy_client: DummyClient):
    article = Article(
        client=dummy_client,
        data={"urn": "urn:article:one", "title": "Example"},
        sync=False,
    )

    dummy_client.queue_response(
        "get",
        f"artifacts/{ARTIFACT_ID}",
        StubResponse(
            200,
            {
                "result": {
                    "id": ARTIFACT_ID,
                    "parent_urn": "urn:article:one",
                    "title": "Supplementary PDF",
                    "description": "Attached document",
                    "type": "artifact",
                    "file_url": "https://files.example.com/a.pdf",
                    "file_type": "application/pdf",
                    "file_size": 128,
                }
            },
        ),
    )

    artifact = article.artifacts[ARTIFACT_ID]

    assert artifact.id == ARTIFACT_ID
    assert artifact.parent_urn == "urn:article:one"


def test_parent_entity_artifacts_create_injects_parent_urn(dummy_client: DummyClient):
    article = Article(
        client=dummy_client,
        data={"urn": "urn:article:one", "title": "Example"},
        sync=False,
    )

    dummy_client.queue_response(
        "post",
        "artifacts",
        StubResponse(
            200,
            {
                "result": {
                    "id": ARTIFACT_ID,
                    "parent_urn": "urn:article:one",
                    "title": "Supplementary PDF",
                    "description": "Attached document",
                    "type": "artifact",
                    "file_url": "https://files.example.com/a.pdf",
                    "file_type": "application/pdf",
                    "file_size": 128,
                }
            },
        ),
    )

    created = article.artifacts.create(
        title="Supplementary PDF",
        description="Attached document",
        file_url="https://files.example.com/a.pdf",
        file_type="application/pdf",
        file_size=128,
    )

    method, endpoint, body, _kwargs = dummy_client.calls[-1]
    assert method == "post"
    assert endpoint == "artifacts"
    assert body["parent_urn"] == "urn:article:one"
    assert created.parent_urn == "urn:article:one"


def test_artifacts_proxy_upload_posts_multipart_form_data(
    dummy_client: DummyClient, tmp_path: Path
):
    file_path = tmp_path / "artifact.pdf"
    file_path.write_bytes(b"%PDF-1.4")

    dummy_client.queue_response(
        "post",
        "artifacts/upload",
        StubResponse(
            200,
            {
                "result": {
                    "id": ARTIFACT_ID,
                    "parent_urn": "urn:article:one",
                    "title": "Supplementary PDF",
                    "description": "Attached document",
                    "type": "artifact",
                    "file_url": "https://files.example.com/a.pdf",
                    "file_type": "application/pdf",
                    "file_size": 128,
                }
            },
        ),
    )

    proxy = ArtifactsProxy(dummy_client)
    created = proxy.upload(
        file_path,
        parent_urn="urn:article:one",
        title="Supplementary PDF",
        description="Attached document",
        language="en",
    )

    method, endpoint, json_body, kwargs = dummy_client.calls[-1]
    assert method == "post"
    assert endpoint == "artifacts/upload"
    assert json_body is None
    assert kwargs["data"] == {
        "parent_urn": "urn:article:one",
        "title": "Supplementary PDF",
        "description": "Attached document",
        "language": "en",
    }
    assert kwargs["files"]["file"][0] == "artifact.pdf"
    assert created.id == ARTIFACT_ID


def test_parent_artifacts_proxy_upload_injects_parent_urn(
    dummy_client: DummyClient, tmp_path: Path
):
    file_path = tmp_path / "artifact.pdf"
    file_path.write_bytes(b"%PDF-1.4")

    dummy_client.queue_response(
        "post",
        "artifacts/upload",
        StubResponse(
            200,
            {
                "result": {
                    "id": ARTIFACT_ID,
                    "parent_urn": "urn:article:one",
                    "title": "Supplementary PDF",
                    "description": "Attached document",
                    "type": "artifact",
                    "file_url": "https://files.example.com/a.pdf",
                    "file_type": "application/pdf",
                    "file_size": 128,
                }
            },
        ),
    )

    article = Article(
        client=dummy_client,
        data={"urn": "urn:article:one", "title": "Example"},
        sync=False,
    )
    created = article.artifacts.upload(file_path, title="Supplementary PDF")

    method, endpoint, json_body, kwargs = dummy_client.calls[-1]
    assert method == "post"
    assert endpoint == "artifacts/upload"
    assert json_body is None
    assert kwargs["data"]["parent_urn"] == "urn:article:one"
    assert created.parent_urn == "urn:article:one"


def test_parent_artifacts_proxy_upload_updates_parent_embedded_records(
    dummy_client: DummyClient, tmp_path: Path
):
    file_path = tmp_path / "artifact.pdf"
    file_path.write_bytes(b"%PDF-1.4")

    dummy_client.queue_response(
        "post",
        "artifacts/upload",
        StubResponse(
            200,
            {
                "result": {
                    "id": ARTIFACT_ID,
                    "parent_urn": TEXTBOOK_URN,
                    "title": "Nutrition Basics PDF",
                    "description": "Attached textbook PDF",
                    "type": "artifact",
                    "file_url": "https://files.example.com/t.pdf",
                    "file_type": "application/pdf",
                    "file_size": 256,
                }
            },
        ),
    )

    textbook = Textbook(
        client=dummy_client,
        data={"urn": TEXTBOOK_URN, "title": "Nutrition Basics"},
        sync=False,
    )

    created = textbook.artifacts.upload(file_path, title="Nutrition Basics PDF")

    assert created.parent_urn == TEXTBOOK_URN
    assert textbook.artifact_record == {
        "id": ARTIFACT_ID,
        "parent_urn": TEXTBOOK_URN,
        "title": "Nutrition Basics PDF",
        "description": "Attached textbook PDF",
        "type": "artifact",
        "file_url": "https://files.example.com/t.pdf",
        "file_type": "application/pdf",
        "file_size": 256,
    }
    assert textbook.artifacts[0].id == ARTIFACT_ID
