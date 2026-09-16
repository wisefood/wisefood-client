"""Turning a textbook PDF into retrievable passages.

The gap this fills, stated plainly: the catalog has accepted textbook
passages for a while, and something *outside* the platform produced them —
the console's own wording is "produced by the external chunker". So a
textbook could be registered but never read, and the step in between was a
person running a script nobody here owns.

Unlike guideline extraction, this uses no model. A dietary guide's rules have
to be *understood* to be extracted, which is why that pipeline renders pages
and asks a vision model. A textbook passage is just a span of the book with
enough context to be retrieved, so the work is text extraction and sensible
boundaries. That difference is the whole reason this runs in seconds rather
than minutes, and why it needs no queue behind it.

What "sensible boundaries" means here:

* **Headings carry.** A passage retrieved out of a 600-page book is useless
  without knowing it came from "Chapter 7 › Protein requirements", so the
  heading stack travels with every passage as its `structure_path`.
* **Paragraphs are not split** unless one is longer than a whole passage. A
  chunk that begins mid-sentence reads as noise to whoever it is shown to.
* **Passages overlap**, because the answer to a question often straddles the
  boundary somebody's chunker happened to pick.

There is deliberately no duplicate filter. A first attempt dropped a passage
whose text matched the one before it, which looked tidy and was wrong twice
over: prose in a real book repeats (a glossary, a table of near-identical
rows), so it discarded whole sections; and every passage carries `char_start`
and `char_end` as offsets into the book, which stop meaning anything the
moment a span is silently skipped. The thing actually worth preventing — a
trailing passage holding nothing but the overlap carried from its predecessor
— is prevented exactly, by tracking whether any new text was added.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

#: Default passage size. The ceiling is not a preference — it is the
#: embedding model's context, and a passage longer than that is silently
#: truncated at embedding time, so the tail of it is stored but never found.
#: 1200 characters sits under a 384-token budget with room for the heading.
TARGET_CHARS = 1200
OVERLAP_CHARS = 150

#: A line this long is prose that happens to be big, not a heading.
MAX_HEADING_CHARS = 120

#: How much larger than body text a line must be to count as a heading.
HEADING_RATIO = 1.15
BOLD_HEADING_RATIO = 1.04

EXTRACTOR_NAME = "wisefood-mcp/passages"


class PassageExtractionError(RuntimeError):
    """The PDF could not be read as text."""


@dataclass
class _Line:
    text: str
    size: float
    bold: bool
    page_no: int


@dataclass
class _Block:
    """A paragraph or a heading, with where it came from."""

    text: str
    page_no: int
    is_heading: bool
    level: float = 0.0
    """Larger means higher in the hierarchy. The font size, in practice."""


@dataclass
class _Chunk:
    text: str = ""
    page_no: int = 1
    structure_path: List[str] = field(default_factory=list)
    char_start: int = 0
    #: Whether anything has been added since this chunk began. A chunk holding
    #: only the overlap carried from the one before it has nothing new in it,
    #: and emitting it would store a duplicate for retrieval to find twice.
    has_new: bool = False


def _open(pdf_path: str):
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover - deployment shape
        raise PassageExtractionError(
            "PyMuPDF is not installed; textbook passages cannot be extracted here"
        ) from exc
    try:
        return fitz.open(pdf_path)
    except Exception as exc:  # noqa: BLE001
        raise PassageExtractionError(f"that file could not be opened as a PDF: {exc}") from exc


def _lines(document) -> List[_Line]:
    """Every line of the book, with the type size it was set in."""
    out: List[_Line] = []
    for page_index, page in enumerate(document, start=1):
        try:
            content = page.get_text("dict")
        except Exception:  # noqa: BLE001 — one unreadable page is not a failure
            logger.warning("passages: page %s could not be read", page_index)
            continue
        for block in content.get("blocks", []):
            for line in block.get("lines", []):
                spans = line.get("spans", []) or []
                text = "".join(span.get("text", "") for span in spans).strip()
                if not text:
                    continue
                sizes = [float(span.get("size") or 0) for span in spans]
                # Bit 4 of `flags` is PyMuPDF's bold marker.
                bold = any(int(span.get("flags") or 0) & 2 ** 4 for span in spans)
                out.append(_Line(text=text, size=max(sizes) if sizes else 0.0,
                                 bold=bold, page_no=page_index))
    return out


def _body_size(lines: List[_Line]) -> float:
    """The size most of the book is set in — the baseline headings stand out from.

    By character count rather than by line, because a book with many short
    headed sections would otherwise let its headings outvote its prose.
    """
    weights: Counter = Counter()
    for line in lines:
        weights[round(line.size, 1)] += len(line.text)
    return weights.most_common(1)[0][0] if weights else 0.0


def _is_heading(line: _Line, body: float) -> bool:
    if not body or len(line.text) > MAX_HEADING_CHARS:
        return False
    if line.size >= body * HEADING_RATIO:
        return True
    # Bold and a little larger also reads as a heading; bold alone does not,
    # or every emphasised term in the prose becomes a section.
    return line.bold and line.size >= body * BOLD_HEADING_RATIO


def _blocks(lines: List[_Line], body: float) -> List[_Block]:
    """Group lines into paragraphs, keeping headings separate.

    PDFs have no paragraphs — only lines that happen to sit under each other —
    so a paragraph ends where a heading starts, where the page changes, or
    where a line ends in a full stop and the next begins a new sentence.
    """
    out: List[_Block] = []
    buffer: List[str] = []
    buffer_page = 1

    def flush():
        nonlocal buffer
        if buffer:
            text = _join(buffer)
            if text:
                out.append(_Block(text=text, page_no=buffer_page, is_heading=False))
            buffer = []

    for line in lines:
        if _is_heading(line, body):
            flush()
            out.append(_Block(text=line.text, page_no=line.page_no,
                              is_heading=True, level=line.size))
            continue
        if not buffer:
            buffer_page = line.page_no
        buffer.append(line.text)
    flush()
    return out


def _join(lines: List[str]) -> str:
    """Re-join lines into prose, healing the hyphens a PDF breaks words with."""
    text = ""
    for line in lines:
        if text.endswith("-") and not text.endswith(("--", " -")):
            text = text[:-1] + line.lstrip()
        elif text:
            text += " " + line.strip()
        else:
            text = line.strip()
    return re.sub(r"\s+", " ", text).strip()


def _path_after(stack: List[Tuple[float, str]], block: _Block) -> List[Tuple[float, str]]:
    """Apply a heading to the stack: pop everything it outranks, then push."""
    kept = [entry for entry in stack if entry[0] > block.level]
    kept.append((block.level, block.text))
    # A stack deeper than this is usually the detector mistaking emphasis for
    # structure; keeping the top levels loses nothing a reader needs.
    return kept[-4:]


def _split_long(text: str, target: int) -> List[str]:
    """Break a paragraph that is longer than a whole passage, at sentences."""
    if len(text) <= target:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out, current = [], ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > target:
            out.append(current)
            current = sentence
        elif current:
            current += " " + sentence
        else:
            current = sentence
        # A single sentence longer than the target — a table row, usually.
        while len(current) > target:
            out.append(current[:target])
            current = current[target:]
    if current:
        out.append(current)
    return out


def _tail(text: str, overlap: int) -> str:
    """The end of a passage, to begin the next one with.

    Cut at a sentence boundary where there is one nearby, so the overlap reads
    as a sentence rather than as a fragment somebody has to decode.
    """
    if overlap <= 0 or len(text) <= overlap:
        return ""
    window = text[-overlap:]
    match = re.search(r"(?<=[.!?])\s+", window)
    return window[match.end():] if match else window


def extract_passages(pdf_path: str, *, target_chars: int = TARGET_CHARS,
                     overlap_chars: int = OVERLAP_CHARS) -> Dict[str, Any]:
    """Read a textbook PDF into passages ready for the catalog.

    Returns the `replace` payload's content: `passages`, `page_count` and a
    `structure_tree` of the headings found, plus counts worth reporting.
    """
    target_chars = max(200, int(target_chars))
    overlap_chars = max(0, min(int(overlap_chars), target_chars // 2))

    document = _open(pdf_path)
    try:
        page_count = document.page_count
        lines = _lines(document)
    finally:
        document.close()

    if not lines:
        raise PassageExtractionError(
            "this PDF has no extractable text — it is probably scanned images, "
            "which needs OCR rather than this extractor")

    body = _body_size(lines)
    blocks = _blocks(lines, body)

    passages: List[Dict[str, Any]] = []
    headings: List[Dict[str, Any]] = []
    stack: List[Tuple[float, str]] = []
    cursor = 0           # offset into the document's text, for char_start/end
    chunk = _Chunk()
    sequence = 0

    def emit():
        nonlocal chunk, cursor, sequence
        text = chunk.text.strip()
        if not text or not chunk.has_new:
            # Nothing, or nothing but the overlap. Either way there is no
            # passage here — keep the heading context for whatever comes next.
            chunk = _Chunk(page_no=chunk.page_no,
                           structure_path=list(chunk.structure_path))
            return
        start = cursor
        cursor += len(text)
        passages.append({
            "page_no": chunk.page_no,
            "sequence_no": sequence,
            "text": text,
            "char_start": start,
            "char_end": cursor,
            "structure_path": list(chunk.structure_path),
        })
        sequence += 1
        carry = _tail(text, overlap_chars).strip()
        chunk = _Chunk(text=carry, page_no=chunk.page_no,
                       structure_path=list(chunk.structure_path))

    for block in blocks:
        if block.is_heading:
            # A heading starts a new passage: a chunk that spans a section
            # break belongs to neither section.
            emit()
            stack = _path_after(stack, block)
            path = [title for _level, title in stack]
            headings.append({"title": block.text, "page_no": block.page_no,
                             "path": path})
            chunk = _Chunk(page_no=block.page_no, structure_path=path)
            continue

        for piece in _split_long(block.text, target_chars):
            if chunk.text and len(chunk.text) + len(piece) + 1 > target_chars:
                emit()
            if not chunk.text:
                chunk.page_no = block.page_no
            chunk.text = f"{chunk.text} {piece}".strip() if chunk.text else piece
            chunk.has_new = True
            if len(chunk.text) >= target_chars:
                emit()
    emit()

    return {
        "page_count": page_count,
        "passages": passages,
        "structure_tree": headings,
        "extractor_name": EXTRACTOR_NAME,
        "body_font_size": body,
        "headings_found": len(headings),
        "characters": cursor,
    }
