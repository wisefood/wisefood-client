# Artifacts

An **artifact** is a file (a PDF, dataset, image, …) attached to another entity. Every
artifact is UUID-addressed and bound to a **parent** via `parent_urn` — an article, a
guide, a textbook, or an FCTable.

## What it is

| | |
|---|---|
| Entity class | `Artifact` |
| Collection | `client.artifacts` (global) · `entity.artifacts` (parent-bound) |
| Endpoint | `artifacts` |
| Identifier | UUID (`id`) |
| Belongs to | a parent entity (`parent_urn`) |

## Field reference

| Field | Type | Notes |
|-------|------|-------|
| `id` | `str` | Read-only. |
| `parent_urn` | `str` | Read-only — the owning entity. |
| `type` | `str` | Read-only. |
| `title` | `str` | |
| `description` | `str` | |
| `file_url` | `str` | Public/served URL. |
| `file_s3_url` | `str` | Backing object-store URL. |
| `file_type` | `str` | MIME/type — required by the update schema. |
| `file_size` | `int` | Bytes. |
| `language` | `str` | |
| `creator` / `created_at` / `updated_at` | `str` | Read-only. |

## Uploading

Upload a file and create the artifact in a single request. `file` may be a path or an
open binary file object:

```python
art = client.artifacts.upload(
    "report.pdf",
    parent_urn="urn:guide:national-dietary-guidelines-2023",
    title="Source PDF",
    description="Original published document",
    language="en",
)
print(art.id, art.file_size)
```

## Downloading

```python
# Stream straight to a local path (creates parent dirs as needed)
path = client.artifacts.download_to(art.id, "./out/report.pdf")

# Or get the raw streamed requests.Response to handle yourself
resp = client.artifacts.download(art.id, stream=True)
for chunk in resp.iter_content(chunk_size=8192):
    ...

# The same methods exist on a loaded artifact:
art.download_to("./out/report.pdf")
art.download(stream=True)
```

## Parent-bound artifacts

Any URN-backed entity exposes `entity.artifacts`, a proxy already scoped to that parent —
you don't pass `parent_urn`:

```python
guide = client.guides["national-dietary-guidelines-2023"]

# Upload under this guide
guide.artifacts.upload("appendix.pdf", title="Appendix")

# Iterate / look up this guide's artifacts
for a in guide.artifacts:
    print(a.title, a.file_type, a.file_size)
```

When a parent entity's API response already embeds its artifacts, the proxy uses those
records directly (no extra request), and newly uploaded/created artifacts are folded back
into the parent's embedded list.

## Updating an artifact

```python
art.title = "Source PDF (revised)"   # auto-syncs
```

```{note}
The server's update schema requires `file_type`, so the client always includes it when
sending a partial artifact update — you don't need to set it yourself.
```

## Gotchas

- Artifacts are addressed by **UUID**, not a slug or URN.
- An artifact belongs to exactly one parent; fetching one through a parent-bound proxy
  validates the `parent_urn` and raises `KeyError` on a mismatch.
- `download()` returns a `requests.Response`; use `download_to()` when you just want the
  bytes on disk.
