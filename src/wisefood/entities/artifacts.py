from os import PathLike
from pathlib import Path
from typing import IO, Any, Dict, Optional, Tuple, Union

from .base import BaseEntity, BaseCollectionProxy, Field

UploadFile = Union[str, PathLike, IO[bytes]]
DownloadPath = Union[str, PathLike]


def _write_download_response(response, path: DownloadPath, *, chunk_size: int = 8192) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        with destination.open("wb") as handle:
            iter_content = getattr(response, "iter_content", None)

            if callable(iter_content):
                for chunk in iter_content(chunk_size=chunk_size):
                    if chunk:
                        handle.write(chunk)
            else:
                content = getattr(response, "content", b"")
                if content:
                    handle.write(content)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()

    return destination


class Artifact(BaseEntity):
    """
    Schema-backed entity for /artifacts.

    Artifacts are addressed by UUIDs instead of URNs and are bound to a parent
    entity via `parent_urn`.
    """

    ENDPOINT = "artifacts"
    IDENTIFIER_FIELD = "id"
    IMMUTABLE_FIELDS = {
        "id",
        "parent_urn",
        "type",
        "creator",
        "created_at",
        "updated_at",
    }

    id: str = Field("id", read_only=True)
    parent_urn: str = Field("parent_urn", read_only=True)
    title: str = Field("title", default="")
    description: Optional[str] = Field("description")
    type: str = Field("type", default="artifact", read_only=True)
    creator: Optional[str] = Field("creator", read_only=True)
    created_at: Optional[str] = Field("created_at", read_only=True)
    updated_at: Optional[str] = Field("updated_at", read_only=True)
    file_url: Optional[str] = Field("file_url")
    file_s3_url: Optional[str] = Field("file_s3_url")
    file_type: Optional[str] = Field("file_type")
    file_size: Optional[int] = Field("file_size")
    language: Optional[str] = Field("language")

    def save(self, *, only_dirty: bool = False) -> None:
        """
        Persist local changes.

        The server-side update schema requires `file_type`, so we include it
        whenever we are sending a partial artifact update.
        """
        if only_dirty and self._dirty_fields:
            body = {
                key: self.data[key]
                for key in self._dirty_fields
                if key in self.data and key not in self.IMMUTABLE_FIELDS
            }

            if "file_type" not in body and "file_type" in self.data:
                body["file_type"] = self.data["file_type"]

            if not body:
                return

            full = self.normalize_identifier(self.identifier)
            resp = self.client.patch(f"{self.ENDPOINT}/{full}", json=body)
            payload = resp.json()
            self.data = self._extract_result(payload)
            self._dirty_fields.clear()
            return

        super().save(only_dirty=only_dirty)

    def download(self, *, stream: bool = False, **kwargs):
        """Download the file associated with this artifact."""
        full = self.normalize_identifier(self.identifier)
        request_kwargs = dict(kwargs)
        if stream:
            request_kwargs["stream"] = True
        return self.client.request(
            "GET",
            f"{self.ENDPOINT}/{full}/download",
            **request_kwargs,
        )

    def download_to(
        self,
        path: DownloadPath,
        *,
        chunk_size: int = 8192,
        **kwargs,
    ) -> Path:
        """Download the file associated with this artifact to a local path."""
        response = self.download(stream=True, **kwargs)
        return _write_download_response(response, path, chunk_size=chunk_size)


class ArtifactsProxy(BaseCollectionProxy):
    ENTITY_CLS = Artifact
    ENDPOINT = "artifacts"

    def download(self, identifier: str, *, stream: bool = False, **kwargs):
        """Download the file associated with an artifact."""
        full = self.ENTITY_CLS.normalize_identifier(identifier)
        request_kwargs = dict(kwargs)
        if stream:
            request_kwargs["stream"] = True
        return self.client.request(
            "GET",
            f"{self.ENDPOINT}/{full}/download",
            **request_kwargs,
        )

    def download_to(
        self,
        identifier: str,
        path: DownloadPath,
        *,
        chunk_size: int = 8192,
        **kwargs,
    ) -> Path:
        """Download an artifact to a local path."""
        response = self.download(identifier, stream=True, **kwargs)
        return _write_download_response(response, path, chunk_size=chunk_size)

    def upload(
        self,
        file: UploadFile,
        *,
        parent_urn: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Artifact:
        """Upload a file and create an artifact in a single request."""
        data: Dict[str, Any] = {"parent_urn": parent_urn}
        if title is not None:
            data["title"] = title
        if description is not None:
            data["description"] = description
        if language is not None:
            data["language"] = language

        opened_file, file_payload = self._prepare_upload_file(file)
        try:
            resp = self.client.post(
                f"{self.ENDPOINT}/upload",
                data=data,
                files={"file": file_payload},
            )
        finally:
            if opened_file is not None:
                opened_file.close()

        payload = resp.json()
        result = self.ENTITY_CLS._extract_result(payload)
        return self.ENTITY_CLS(client=self.client, data=result)

    def _prepare_upload_file(
        self, file: UploadFile
    ) -> Tuple[Optional[IO[bytes]], Tuple[str, IO[bytes]]]:
        if isinstance(file, (str, PathLike)):
            path = Path(file)
            opened_file = path.open("rb")
            return opened_file, (path.name, opened_file)

        file_name = getattr(file, "name", "upload.bin")
        filename = Path(str(file_name)).name
        return None, (filename, file)


class ParentArtifactsProxy(ArtifactsProxy):
    def __init__(
        self,
        client,
        parent_urn: str,
        *,
        parent_entity=None,
        embedded_records: Optional[list[Dict[str, Any]]] = None,
    ) -> None:
        super().__init__(client)
        self.parent_urn = parent_urn
        self.parent_entity = parent_entity
        self._embedded_records = None
        self._embedded_records_by_id: Dict[str, Dict[str, Any]] = {}

        if embedded_records is not None:
            normalized_records = []
            for record in embedded_records:
                if not isinstance(record, dict):
                    continue

                identifier = record.get(self.ENTITY_CLS.IDENTIFIER_FIELD)
                if not isinstance(identifier, str):
                    continue

                normalized_record = dict(record)
                normalized_record.setdefault("parent_urn", self.parent_urn)
                normalized_records.append(normalized_record)
                normalized_id = self.ENTITY_CLS.normalize_identifier(identifier)
                self._embedded_records_by_id[normalized_id] = normalized_record

            self._embedded_records = normalized_records
            self._urns = [
                record[self.ENTITY_CLS.IDENTIFIER_FIELD]
                for record in self._embedded_records
            ]

    def _store_embedded_record(self, artifact: Artifact) -> None:
        record = dict(artifact.data)
        record.setdefault("parent_urn", self.parent_urn)
        normalized_id = self.ENTITY_CLS.normalize_identifier(artifact.identifier)

        if self._embedded_records is None:
            self._embedded_records = []
            self._urns = []

        existing = self._embedded_records_by_id.get(normalized_id)
        if existing is None:
            self._embedded_records.append(record)
            self._urns.append(artifact.identifier)
        else:
            existing_index = self._embedded_records.index(existing)
            self._embedded_records[existing_index] = record

        self._embedded_records_by_id[normalized_id] = record

        if self.parent_entity is not None:
            artifacts_payload = list(self._embedded_records)
            self.parent_entity.data["artifacts"] = artifacts_payload

    def _fetch_urns(self, *, limit: int, offset: int = 0):
        if self._embedded_records is not None:
            stop = offset + limit
            return self._urns[offset:stop]

        resp = self.client.get(
            self.ENDPOINT,
            parent_urn=self.parent_urn,
            limit=limit,
            offset=offset,
        )
        payload = resp.json()
        return self._parse_list_result(payload)

    def _get_entity(self, urn: str, *, lazy: bool = False):
        normalized_id = self.ENTITY_CLS.normalize_identifier(urn)
        embedded_record = self._embedded_records_by_id.get(normalized_id)
        if embedded_record is not None:
            return self.ENTITY_CLS(client=self.client, data=dict(embedded_record))

        entity = super()._get_entity(urn, lazy=lazy)
        if lazy:
            return entity
        if entity.parent_urn != self.parent_urn:
            raise KeyError(
                f"Artifact '{urn}' does not belong to parent '{self.parent_urn}'."
            )
        return entity

    def create(
        self,
        *,
        urn: Optional[str] = None,
        identifier: Optional[str] = None,
        **fields,
    ):
        payload = dict(fields)
        payload["parent_urn"] = self.parent_urn
        artifact = super().create(
            urn=urn,
            identifier=identifier,
            **payload,
        )
        self._store_embedded_record(artifact)
        return artifact

    def upload(
        self,
        file: UploadFile,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Artifact:
        artifact = super().upload(
            file,
            parent_urn=self.parent_urn,
            title=title,
            description=description,
            language=language,
        )
        self._store_embedded_record(artifact)
        return artifact
