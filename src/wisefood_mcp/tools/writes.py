"""Writing to the catalog. Every tool here is gated twice.

First by :func:`wisefood_mcp.stores.require_approved` — no approved proposal,
no write, and there is no tool that approves. Second by
``ctx.writes_enabled`` — Phase 1 ships with it off, so the tools exist, the
model can see what integration *would* involve, and nothing lands until the
flag is turned on in Phase 2 with the guide pipeline behind it.

The order matters and is deliberate: the approval check runs first so that a
model probing a disabled deployment still learns the real rule ("approval
required"), not the temporary one.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from wisefood_mcp.registry import ToolContext, ToolError, ToolRegistry, WritesDisabled
from wisefood_mcp.stores import content_permitted, require_approved


def _gate(ctx: ToolContext, proposal_id: str, *, copies_content: bool):
    proposal = require_approved(ctx.proposal_store, proposal_id)
    if copies_content and not content_permitted(proposal):
        raise ToolError(
            "this proposal's licence does not permit copying content in; only a "
            "pointer (title, URL, publisher) may be registered",
            code="licence_forbids_content", licence=proposal.licence,
        )
    if not ctx.writes_enabled:
        raise WritesDisabled(
            "catalog writes are switched off in this deployment (Phase 1); the "
            "proposal is approved and will run when they are enabled"
        )
    if ctx.data_client is None:
        raise ToolError("no catalog client is configured")
    return proposal


def _provenance(ctx: ToolContext, proposal) -> Dict[str, Any]:
    """What every created entity carries about where it came from."""
    return {
        "integration": {
            "proposal_id": proposal.id,
            "source_url": proposal.source_url,
            "approved_by": proposal.approved_by,
            "approved_at": proposal.approved_at,
            "licence": proposal.licence,
            "licence_evidence": proposal.licence_evidence,
            "licence_override_reason": proposal.licence_override_reason,
            "created_by_tool": "wisefood-mcp",
            "actor": ctx.actor,
        }
    }


def _create(ctx: ToolContext, proxy_name: str, proposal_id: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    proposal = _gate(ctx, proposal_id, copies_content=bool(spec.get("content")))
    proxy = getattr(ctx.data_client, proxy_name)
    fields = dict(spec)
    fields.setdefault("url", proposal.source_url)
    if proposal.licence and not fields.get("license"):
        fields["license"] = proposal.licence
    extras = dict(fields.get("extras") or {})
    extras.update(_provenance(ctx, proposal))
    fields["extras"] = extras
    entity = proxy.create(**fields)
    data = entity.dict() if hasattr(entity, "dict") else dict(entity)
    urn = data.get("urn") or data.get("id")
    ctx.proposal_store.update(proposal_id, result={**proposal.result, "urn": urn})
    return {"urn": urn, "kind": proxy_name, "proposal_id": proposal_id}


def create_guide(ctx: ToolContext, proposal_id: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Create a national dietary guide from an approved proposal.

    :param proposal_id: an approved proposal
    :param spec: guide fields — title, description, region, language, organization_urn, publication_date, …
    """
    return _create(ctx, "guides", proposal_id, spec)


def create_textbook(ctx: ToolContext, proposal_id: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Create a textbook from an approved proposal.

    :param proposal_id: an approved proposal
    :param spec: textbook fields — title, authors, publisher, doi, language, …
    """
    return _create(ctx, "textbooks", proposal_id, spec)


def create_article(ctx: ToolContext, proposal_id: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Create a scientific article from an approved proposal.

    :param proposal_id: an approved proposal
    :param spec: article fields — title, abstract, keywords, topics, …
    """
    return _create(ctx, "articles", proposal_id, spec)


def create_fctable(ctx: ToolContext, proposal_id: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Create a food composition table from an approved proposal.

    Registers a reference to the table, with whatever `profile_fctable`
    measured about it. There is no row store behind this entity — an FCT here
    is a pointer to a table, not a copy of one.

    :param proposal_id: an approved proposal
    :param spec: fctable fields — title, compiling_institution, database_name,
        nutrient_coverage, number_of_entries, completeness_percent, …
    """
    return _create(ctx, "fctables", proposal_id, spec)


def upload_artifact(ctx: ToolContext, proposal_id: str, parent_urn: str,
                    pending_artifact: str, title: Optional[str] = None) -> Dict[str, Any]:
    """Attach a fetched file to a catalog entity as its artifact.

    :param proposal_id: an approved proposal
    :param parent_urn: the guide/textbook/article the file belongs to
    :param pending_artifact: the handle ``fetch_url`` returned for a PDF
    :param title: optional artifact title
    """
    proposal = _gate(ctx, proposal_id, copies_content=True)
    from wisefood_mcp.tools.research import pending_artifact_path

    path = pending_artifact_path(pending_artifact)
    artifact = ctx.data_client.artifacts.upload(
        str(path), parent_urn=parent_urn,
        title=title or proposal.title,
        description=f"Fetched from {proposal.source_url} for proposal {proposal.id}",
    )
    data = artifact.dict() if hasattr(artifact, "dict") else dict(artifact)
    artifact_id = data.get("id") or data.get("uuid")
    ctx.proposal_store.update(proposal_id, result={**proposal.result, "artifact_id": artifact_id})
    return {"artifact_id": artifact_id, "parent_urn": parent_urn}


def _core(ctx: ToolContext, proposal_id: str, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    proposal = _gate(ctx, proposal_id, copies_content=True)
    if ctx.core_post is None:
        raise ToolError("no core API transport is configured for pipeline calls")
    result = ctx.core_post(path, body)
    jobs = list(proposal.result.get("jobs", [])) + [{"path": path, "response": result}]
    ctx.proposal_store.update(proposal_id, result={**proposal.result, "jobs": jobs})
    return result


def enqueue_guideline_extraction(ctx: ToolContext, proposal_id: str, artifact_uuid: str,
                                 guide_urn: str) -> Dict[str, Any]:
    """Queue the PDF→guideline extraction for an uploaded guide artifact.

    :param proposal_id: an approved proposal
    :param artifact_uuid: the uploaded artifact
    :param guide_urn: the guide it belongs to, so rules keep their population context
    """
    return _core(ctx, proposal_id, f"/api/v1/guidelines/extract/{artifact_uuid}",
                 {"guide_id": guide_urn})


def import_guidelines(ctx: ToolContext, proposal_id: str, artifact_uuid: str,
                      guide_urn: str, dry_run: bool = True) -> Dict[str, Any]:
    """Import extracted guideline entries into the catalog under their guide.

    The body says ``guide_id`` because that is what the core route's request
    model calls the field, whatever we call it here; sending ``guide_urn``
    gets a 422 and no import.

    ``dry_run`` defaults to true on both sides, so the caller that forgets it
    gets a preview rather than an unreviewed write. Run it once to see what
    would be created, then again with ``dry_run=False`` to create it.

    :param proposal_id: an approved proposal
    :param artifact_uuid: the artifact whose extraction succeeded
    :param guide_urn: the guide to import under
    :param dry_run: preview only; nothing is created
    """
    return _core(ctx, proposal_id, f"/api/v1/guidelines/import/{artifact_uuid}",
                 {"guide_id": guide_urn, "dry_run": bool(dry_run)})


def guideline_extraction_status(ctx: ToolContext, proposal_id: str,
                                artifact_uuid: str) -> Dict[str, Any]:
    """Check how a queued guideline extraction is getting on.

    Reads rather than writes, but it is part of the integration pipeline and
    carries no meaning outside one, so it is grouped and gated with the tools
    that do write. What comes back is trimmed to the progress fields: the
    full response carries every extracted rule, which is not what a progress
    check is for.

    :param proposal_id: an approved proposal
    :param artifact_uuid: the artifact being extracted
    """
    _gate(ctx, proposal_id, copies_content=False)
    if ctx.core_get is None:
        raise ToolError("no core API transport is configured for pipeline calls")
    state = ctx.core_get(f"/api/v1/guidelines/extract/{artifact_uuid}") or {}
    result = state.get("result") or {}
    return {
        "artifact_uuid": artifact_uuid,
        "status": state.get("status"),
        "current_page": state.get("current_page"),
        "total_pages": state.get("total_pages"),
        "error": state.get("error"),
        "guideline_count": len(result.get("guidelines") or []),
    }


def enqueue_article_enrichment(ctx: ToolContext, proposal_id: str,
                               article_urn: str, force: bool = False) -> Dict[str, Any]:
    """Queue enrichment for a catalog article — keywords, study type, Q&A.

    An article is a usable catalog entry the moment it is created; enrichment
    is what makes it findable and answerable. Queued rather than run here: the
    on-demand enrichment worker drains it, independently of the corpus
    sweeper, so this keeps working while the sweeper is paused.

    :param proposal_id: an approved proposal
    :param article_urn: the article to enrich
    :param force: re-enrich an article that was already processed
    """
    return _core(ctx, proposal_id,
                 f"/api/v1/enrich/articles/{article_urn}",
                 {"force": bool(force), "requested_by": ctx.actor})


def article_enrichment_status(ctx: ToolContext, proposal_id: str,
                              article_urn: str) -> Dict[str, Any]:
    """Check how a queued article enrichment is getting on.

    Trimmed to the progress fields for the same reason the guideline one is:
    the full response carries everything the last successful run wrote, and a
    progress check is not a result dump.

    :param proposal_id: an approved proposal
    :param article_urn: the article being enriched
    """
    _gate(ctx, proposal_id, copies_content=False)
    if ctx.core_get is None:
        raise ToolError("no core API transport is configured for pipeline calls")
    state = ctx.core_get(f"/api/v1/enrich/articles/{article_urn}") or {}
    return {
        "article_urn": article_urn,
        "status": state.get("status"),
        "error": state.get("error"),
        "processed": state.get("processed"),
        "permanently_failed": state.get("permanently_failed"),
        "wrote": sorted((state.get("result") or {}).keys()),
    }


def extract_textbook_passages(ctx: ToolContext, proposal_id: str, textbook_urn: str,
                              artifact_uuid: str, target_chars: int = 1200,
                              overlap_chars: int = 150) -> Dict[str, Any]:
    """Read an attached textbook PDF into passages and store them.

    The step that was missing: the catalog has accepted passages for a while,
    but something outside the platform produced them, so a textbook could be
    registered and never actually readable. This does it here, with the run
    recorded against the proposal like everything else.

    No model is involved, unlike a guide's extraction — a dietary guide's
    rules have to be understood to be pulled out, whereas a passage is a span
    of the book with enough context to be retrieved. So this takes seconds and
    runs inline rather than behind a queue.

    Replaces whatever that artifact had before, atomically; re-running it
    after a better chunking is a supported thing to do.

    :param proposal_id: an approved proposal
    :param textbook_urn: the textbook these passages belong to
    :param artifact_uuid: the uploaded PDF to read
    :param target_chars: how long a passage should be
    :param overlap_chars: how much of each passage repeats the one before
    """
    proposal = _gate(ctx, proposal_id, copies_content=True)

    from wisefood_mcp.passages import PassageExtractionError, extract_passages

    path = _local_pdf(ctx, proposal, artifact_uuid)
    try:
        extracted = extract_passages(str(path), target_chars=target_chars,
                                     overlap_chars=overlap_chars)
    except PassageExtractionError as exc:
        raise ToolError(str(exc), code="unreadable_pdf",
                        artifact_uuid=artifact_uuid) from exc

    if not extracted["passages"]:
        raise ToolError("that PDF produced no passages", code="no_passages",
                        artifact_uuid=artifact_uuid)

    bound = ctx.data_client.textbook_passages.by_textbook(textbook_urn)
    bound.bulk_replace(
        artifact_id=artifact_uuid,
        passages=extracted["passages"],
        page_count=extracted["page_count"],
        # Deliberately not sent. `bulk_replace` wants a structure *tree* in a
        # shape this package has not verified, and guessing at somebody's
        # request schema is how you get a 422 in production. Each passage
        # already carries its heading stack as `structure_path`, which is what
        # retrieval actually reads; the headings are reported below so a
        # curator can still see what the chunker found.
        structure_tree=None,
        extractor_name=extracted["extractor_name"],
        extractor_run_id=proposal.id,
    )

    result = {
        "textbook_urn": textbook_urn, "artifact_uuid": artifact_uuid,
        "passages": len(extracted["passages"]),
        "page_count": extracted["page_count"],
        "headings_found": extracted["headings_found"],
        "characters": extracted["characters"],
    }
    ctx.proposal_store.update(proposal_id, result={**proposal.result, **result})
    return result


def profile_fctable(ctx: ToolContext, proposal_id: str,
                    pending_artifact: str) -> Dict[str, Any]:
    """Read a food composition table and describe what is in it.

    Not an extractor, and the distinction is the whole design. `FCTable` in
    this catalog is a metadata entity — compiling institution, nutrient
    coverage, number of entries, completeness — with no row-level store behind
    it anywhere. An FCT here is a registered reference to a table, not a copy
    of one, so extracting thousands of rows would produce data with nowhere to
    go.

    What it does instead is the arithmetic a curator would otherwise do by
    hand with a five-thousand-row spreadsheet open: count the entries, list
    the nutrient columns, work out how much of the grid is actually filled.
    The column names it judged from come back with it, so the profile can be
    argued with rather than trusted.

    :param proposal_id: an approved proposal
    :param pending_artifact: the handle ``fetch_url`` returned for the table
    """
    _gate(ctx, proposal_id, copies_content=True)

    from wisefood_mcp.fctables import TableProfileError, profile_table
    from wisefood_mcp.tools.research import pending_artifact_path

    path = pending_artifact_path(pending_artifact)
    try:
        return profile_table(str(path))
    except TableProfileError as exc:
        raise ToolError(str(exc), code="unreadable_table",
                        pending_artifact=pending_artifact) from exc


def _local_pdf(ctx: ToolContext, proposal, artifact_uuid: str):
    """The PDF on disk, from the fetch if it survived or the catalog if not.

    A pending handle is the same bytes we uploaded and costs nothing to reuse.
    It does not survive a pod restart, though, and a retry after one is
    exactly when this runs — so the catalog copy is the fallback rather than
    an error telling somebody to fetch the file again.
    """
    import tempfile
    from pathlib import Path

    from wisefood_mcp.tools.research import pending_artifact_path

    handle = (proposal.metadata or {}).get("pending_artifact")
    if handle:
        try:
            return pending_artifact_path(handle)
        except ToolError:
            pass

    target = Path(tempfile.gettempdir()) / f"wisefood-textbook-{artifact_uuid}.pdf"
    try:
        ctx.data_client.artifacts.download_to(artifact_uuid, str(target))
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"the artifact could not be downloaded: {exc}"[:300],
                        artifact_uuid=artifact_uuid) from exc
    if not target.exists():
        raise ToolError("the artifact downloaded to nothing",
                        artifact_uuid=artifact_uuid)
    return target


def register(registry: ToolRegistry) -> None:
    for fn in (create_guide, create_textbook, create_article, create_fctable,
               upload_artifact,
               enqueue_guideline_extraction, guideline_extraction_status,
               import_guidelines,
               enqueue_article_enrichment, article_enrichment_status,
               extract_textbook_passages, profile_fctable):
        registry.register(fn, write=True)
