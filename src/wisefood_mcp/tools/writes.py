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

from typing import Any, Dict, List, Optional

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
                      guide_urn: str) -> Dict[str, Any]:
    """Import extracted guideline entries into the catalog under their guide.

    :param proposal_id: an approved proposal
    :param artifact_uuid: the artifact whose extraction succeeded
    :param guide_urn: the guide to import under
    """
    return _core(ctx, proposal_id, f"/api/v1/guidelines/import/{artifact_uuid}",
                 {"guide_urn": guide_urn})


def register(registry: ToolRegistry) -> None:
    for fn in (create_guide, create_textbook, create_article, upload_artifact,
               enqueue_guideline_extraction, import_guidelines):
        registry.register(fn, write=True)
