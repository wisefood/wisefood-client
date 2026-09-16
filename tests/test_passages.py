"""Chunking a textbook into passages.

Built against a real PDF rather than a fixture of pre-extracted text, because
every hard part of this lives in what PyMuPDF hands back: a heading is only a
heading by its type size, a paragraph is only a paragraph because its lines
sit under one another, and words are hyphenated across line breaks. A test
that starts from clean text proves none of it.

What these assert is what a bad chunker gets wrong:

* a passage that starts mid-sentence reads as noise;
* a passage retrieved out of a 600-page book without its chapter is unusable;
* an overlap that is a fragment rather than a sentence is worse than none;
* and a scanned book has no text at all, which must be said rather than
  returned as an empty success.
"""
from __future__ import annotations

import pytest

from wisefood_mcp.passages import (
    PassageExtractionError, TARGET_CHARS, extract_passages,
)

fitz = pytest.importorskip("fitz")


BODY = 11
H1 = 22
H2 = 15


def build_pdf(path, sections):
    """A book: [(heading_size, heading, [paragraph, ...]), ...]."""
    doc = fitz.open()
    for size, heading, paragraphs in sections:
        page = doc.new_page()
        y = 60
        if heading:
            page.insert_text((60, y), heading, fontsize=size)
            y += size + 14
        for paragraph in paragraphs:
            for line in _wrap(paragraph, 68):
                page.insert_text((60, y), line, fontsize=BODY)
                y += BODY + 4
            y += 10
    doc.save(str(path))
    doc.close()
    return str(path)


def _wrap(text, width):
    words, line, out = text.split(), "", []
    for word in words:
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


SENTENCE = ("Protein requirements rise during pregnancy and lactation, and the "
            "evidence for this is consistent across cohorts. ")


@pytest.fixture
def textbook(tmp_path):
    return build_pdf(tmp_path / "textbook.pdf", [
        (H1, "Chapter 7 Macronutrients", [SENTENCE * 6]),
        (H2, "7.1 Protein", [SENTENCE * 8]),
        (H2, "7.2 Fat", [SENTENCE * 4]),
    ])


def test_a_book_becomes_passages_with_positions(textbook):
    out = extract_passages(textbook)
    assert out["page_count"] == 3
    assert out["passages"], "a readable book must produce passages"

    for i, passage in enumerate(out["passages"]):
        assert passage["sequence_no"] == i, "sequence must be dense and in order"
        assert passage["text"].strip() == passage["text"]
        assert passage["char_end"] > passage["char_start"]
        assert passage["char_end"] - passage["char_start"] == len(passage["text"])
        assert 1 <= passage["page_no"] <= 3


def test_every_passage_knows_which_section_it_came_from(textbook):
    """A passage retrieved out of a 600-page book without its chapter is
    unusable — the heading stack is not decoration."""
    out = extract_passages(textbook)
    paths = [tuple(p["structure_path"]) for p in out["passages"]]
    assert all(paths), "no passage may be orphaned from its heading"
    assert ("Chapter 7 Macronutrients",) in paths
    assert ("Chapter 7 Macronutrients", "7.1 Protein") in paths
    assert ("Chapter 7 Macronutrients", "7.2 Fat") in paths


def test_a_subheading_nests_under_its_chapter_rather_than_replacing_it(textbook):
    out = extract_passages(textbook)
    under_protein = [p for p in out["passages"]
                     if p["structure_path"][-1:] == ["7.1 Protein"]]
    assert under_protein
    assert all(p["structure_path"][0] == "Chapter 7 Macronutrients"
               for p in under_protein)


def test_a_passage_never_spans_a_section_break(textbook):
    """A chunk that straddles a heading belongs to neither section."""
    out = extract_passages(textbook)
    for passage in out["passages"]:
        assert "7.1 Protein" not in passage["text"]
        assert "7.2 Fat" not in passage["text"]


def test_passages_respect_the_target_size(textbook):
    out = extract_passages(textbook, target_chars=400, overlap_chars=50)
    # The last passage of a section is whatever is left, so only the ones that
    # were cut for length are bounded.
    oversize = [p for p in out["passages"] if len(p["text"]) > 400 * 1.6]
    assert not oversize, f"{len(oversize)} passages ran well past the target"


def test_passages_overlap_so_an_answer_is_not_cut_in_half(textbook):
    out = extract_passages(textbook, target_chars=400, overlap_chars=120)
    same_section = [p for p in out["passages"]
                    if p["structure_path"][-1:] == ["7.1 Protein"]]
    assert len(same_section) > 1, "this section should have split"
    first, second = same_section[0], same_section[1]
    tail = first["text"][-60:]
    assert any(word in second["text"] for word in tail.split()[:4])


def test_no_overlap_is_honoured(textbook):
    out = extract_passages(textbook, target_chars=400, overlap_chars=0)
    section = [p for p in out["passages"]
               if p["structure_path"][-1:] == ["7.1 Protein"]]
    assert len(section) > 1
    assert not section[1]["text"].startswith(section[0]["text"][-40:])


def test_a_word_broken_across_lines_is_healed(tmp_path):
    """PDFs hyphenate at line ends. "require- ments" is not a word."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((60, 60), "Nutrition Basics", fontsize=H1)
    page.insert_text((60, 100), "Protein require-", fontsize=BODY)
    page.insert_text((60, 116), "ments rise in preg-", fontsize=BODY)
    page.insert_text((60, 132), "nancy considerably.", fontsize=BODY)
    path = tmp_path / "hyphen.pdf"
    doc.save(str(path))
    doc.close()

    text = " ".join(p["text"] for p in extract_passages(str(path))["passages"])
    assert "requirements" in text
    assert "pregnancy" in text
    assert "require- ments" not in text


def test_a_long_paragraph_is_split_at_sentences(tmp_path):
    """A passage that begins mid-sentence reads as noise to whoever sees it."""
    path = build_pdf(tmp_path / "long.pdf",
                     [(H1, "One Section", [SENTENCE * 40])])
    out = extract_passages(str(path), target_chars=500, overlap_chars=0)
    assert len(out["passages"]) > 3
    for passage in out["passages"][1:]:
        first = passage["text"].lstrip()
        assert first[:1].isupper(), f"began mid-sentence: {first[:60]!r}"


def test_emphasis_in_prose_does_not_become_a_section(tmp_path):
    """Bold alone is not a heading, or every emphasised term is a section."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((60, 60), "Real Heading", fontsize=H1)
    y = 100
    for line in _wrap(SENTENCE * 3, 68):
        page.insert_text((60, y), line, fontsize=BODY, fontname="hebo")
        y += BODY + 4
    path = tmp_path / "bold.pdf"
    doc.save(str(path))
    doc.close()

    out = extract_passages(str(path))
    assert out["headings_found"] == 1, "bold body text was read as headings"


def test_a_scanned_book_is_reported_rather_than_returned_empty(tmp_path):
    """Images of text produce nothing, and that needs OCR — not silence."""
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    path = tmp_path / "scanned.pdf"
    doc.save(str(path))
    doc.close()

    with pytest.raises(PassageExtractionError, match="scanned"):
        extract_passages(str(path))


def test_a_file_that_is_not_a_pdf_says_so(tmp_path):
    path = tmp_path / "notapdf.pdf"
    path.write_text("this is just text")
    with pytest.raises(PassageExtractionError):
        extract_passages(str(path))


def test_the_overlap_never_becomes_a_passage_of_its_own(tmp_path):
    """Two things the carry-over can produce and neither is a passage: a tail
    holding nothing new, and a window byte-identical to its predecessor.

    The content here repeats one sentence deliberately — that is the case a
    substring-based check gets wrong, by discarding whole real sections of a
    book whose prose happens to repeat."""
    path = build_pdf(tmp_path / "tail.pdf", [(H1, "S", [SENTENCE * 5])])
    out = extract_passages(str(path), target_chars=300, overlap_chars=140)
    texts = [p["text"] for p in out["passages"]]
    assert texts, "the section must survive"
    assert [p["sequence_no"] for p in out["passages"]] == list(range(len(texts)))
    # Offsets stay contiguous, which is what makes them mean anything.
    for earlier, later in zip(out["passages"], out["passages"][1:]):
        assert later["char_start"] == earlier["char_end"]


def test_defaults_are_sane(textbook):
    out = extract_passages(textbook)
    assert out["extractor_name"] == "wisefood-mcp/passages"
    assert out["characters"] > 0
    assert all(len(p["text"]) <= TARGET_CHARS * 2 for p in out["passages"])
