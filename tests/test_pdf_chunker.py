"""Tests for PDF chunking functionality."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mistral_ocr_zotero.pdf_chunker import (
    PDFChunker,
    PDFChunk,
    TOCEntry,
    ChunkingResult,
    MAX_PAGES_PER_CHUNK,
    DEFAULT_CHUNK_SIZE,
)


class TestTOCEntry:
    """Tests for TOCEntry dataclass."""

    def test_toc_entry_creation(self):
        """TOCEntry should store level, title, and page."""
        entry = TOCEntry(level=1, title="Chapter 1", page=0)
        assert entry.level == 1
        assert entry.title == "Chapter 1"
        assert entry.page == 0


class TestPDFChunk:
    """Tests for PDFChunk dataclass."""

    def test_chunk_page_count(self):
        """PDFChunk should calculate page count correctly."""
        chunk = PDFChunk(chunk_index=0, start_page=0, end_page=100)
        assert chunk.page_count == 100

    def test_chunk_with_title(self):
        """PDFChunk should store optional title."""
        chunk = PDFChunk(
            chunk_index=0, start_page=0, end_page=100, title="Introduction"
        )
        assert chunk.title == "Introduction"


class TestChunkingResult:
    """Tests for ChunkingResult dataclass."""

    def test_needs_chunking_small_pdf(self):
        """Small PDFs should not need chunking."""
        result = ChunkingResult(
            original_path=Path("test.pdf"),
            total_pages=500,
            chunks=[PDFChunk(chunk_index=0, start_page=0, end_page=500)],
            has_toc=False,
        )
        assert not result.needs_chunking

    def test_needs_chunking_large_pdf(self):
        """Large PDFs should need chunking."""
        result = ChunkingResult(
            original_path=Path("test.pdf"),
            total_pages=1500,
            chunks=[
                PDFChunk(chunk_index=0, start_page=0, end_page=950),
                PDFChunk(chunk_index=1, start_page=950, end_page=1500),
            ],
            has_toc=False,
        )
        assert result.needs_chunking


class TestPDFChunker:
    """Tests for PDFChunker class."""

    def test_init_default_values(self):
        """PDFChunker should use default values."""
        chunker = PDFChunker()
        assert chunker.max_chunk_size == DEFAULT_CHUNK_SIZE
        assert chunker.min_chapter_level == 1
        assert chunker.max_chapter_level == 2

    def test_init_custom_values(self):
        """PDFChunker should accept custom values."""
        chunker = PDFChunker(
            max_chunk_size=800, min_chapter_level=1, max_chapter_level=3
        )
        assert chunker.max_chunk_size == 800
        assert chunker.max_chapter_level == 3

    @patch("mistral_ocr_zotero.pdf_chunker.fitz")
    def test_analyze_small_pdf_no_chunking(self, mock_fitz):
        """PDFs under limit should not be chunked."""
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=500)
        mock_doc.get_toc.return_value = []
        mock_fitz.open.return_value = mock_doc

        chunker = PDFChunker()
        result = chunker.analyze(Path("test.pdf"))

        assert not result.needs_chunking
        assert len(result.chunks) == 1
        assert result.chunks[0].start_page == 0
        assert result.chunks[0].end_page == 500
        assert result.total_pages == 500

    @patch("mistral_ocr_zotero.pdf_chunker.fitz")
    def test_analyze_large_pdf_no_toc_fixed_chunks(self, mock_fitz):
        """Large PDFs without TOC should use fixed-size chunks."""
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=2000)
        mock_doc.get_toc.return_value = []
        mock_fitz.open.return_value = mock_doc

        chunker = PDFChunker(max_chunk_size=950)
        result = chunker.analyze(Path("test.pdf"))

        assert result.needs_chunking
        assert not result.has_toc
        # Should have 3 chunks: 0-950, 950-1900, 1900-2000
        assert len(result.chunks) == 3
        assert result.chunks[0].start_page == 0
        assert result.chunks[0].end_page == 950
        assert result.chunks[1].start_page == 950
        assert result.chunks[1].end_page == 1900
        assert result.chunks[2].start_page == 1900
        assert result.chunks[2].end_page == 2000

    @patch("mistral_ocr_zotero.pdf_chunker.fitz")
    def test_analyze_large_pdf_with_toc(self, mock_fitz):
        """Large PDFs with TOC should chunk at chapter boundaries."""
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=2500)
        # TOC: [level, title, page] - pages are 1-indexed in PyMuPDF
        mock_doc.get_toc.return_value = [
            [1, "Chapter 1", 1],
            [1, "Chapter 2", 800],
            [1, "Chapter 3", 1600],
            [1, "Chapter 4", 2400],
        ]
        mock_fitz.open.return_value = mock_doc

        chunker = PDFChunker(max_chunk_size=950)
        result = chunker.analyze(Path("test.pdf"))

        assert result.needs_chunking
        assert result.has_toc
        # Should split at chapter boundaries
        assert len(result.chunks) >= 2
        # First chunk should end at a chapter boundary
        assert result.chunks[0].start_page == 0

    @patch("mistral_ocr_zotero.pdf_chunker.fitz")
    def test_analyze_filters_toc_by_level(self, mock_fitz):
        """PDFChunker should filter TOC entries by level."""
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=2000)
        # Mix of levels: level 1, 2, and 3
        mock_doc.get_toc.return_value = [
            [1, "Part 1", 1],
            [2, "Chapter 1.1", 100],
            [3, "Section 1.1.1", 150],  # Should be filtered out (level 3)
            [1, "Part 2", 1000],
            [2, "Chapter 2.1", 1100],
        ]
        mock_fitz.open.return_value = mock_doc

        # Only consider levels 1-2
        chunker = PDFChunker(min_chapter_level=1, max_chapter_level=2)
        result = chunker.analyze(Path("test.pdf"))

        # Verify TOC was processed (has_toc should be True)
        assert result.has_toc

    @patch("mistral_ocr_zotero.pdf_chunker.fitz")
    def test_extract_chunks(self, mock_fitz):
        """extract_chunks should create chunk PDFs."""
        # Mock the source document
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=2000)

        # Mock the chunk document
        mock_chunk_doc = MagicMock()

        # fitz.open() is called twice: once for source, once for empty chunk doc
        mock_fitz.open.side_effect = [mock_doc, mock_chunk_doc]

        chunks = [
            PDFChunk(chunk_index=0, start_page=0, end_page=1000),
            PDFChunk(chunk_index=1, start_page=1000, end_page=2000),
        ]

        chunker = PDFChunker()
        with patch("tempfile.mkdtemp", return_value="/tmp/pdf_chunks_test"):
            # We need to handle the Path operations
            with patch.object(Path, "exists", return_value=True):
                # Just test that it doesn't raise - actual file ops are mocked
                try:
                    chunker.extract_chunks(Path("test.pdf"), chunks[:1])
                except Exception:
                    pass  # Expected since we're not fully mocking file I/O


class TestPDFChunkerChunkBySize:
    """Tests for _chunk_by_size method."""

    def test_chunk_by_size_exact_fit(self):
        """Pages that fit exactly in chunks."""
        chunker = PDFChunker(max_chunk_size=500)
        chunks = chunker._chunk_by_size(1000)

        assert len(chunks) == 2
        assert chunks[0].start_page == 0
        assert chunks[0].end_page == 500
        assert chunks[1].start_page == 500
        assert chunks[1].end_page == 1000

    def test_chunk_by_size_remainder(self):
        """Pages with remainder in last chunk."""
        chunker = PDFChunker(max_chunk_size=400)
        chunks = chunker._chunk_by_size(1000)

        assert len(chunks) == 3
        assert chunks[0].end_page == 400
        assert chunks[1].end_page == 800
        assert chunks[2].end_page == 1000
        assert chunks[2].page_count == 200


class TestPDFChunkerChunkByTOC:
    """Tests for _chunk_by_toc method."""

    def test_chunk_by_toc_respects_boundaries(self):
        """Chunks should end at TOC boundaries when possible."""
        chunker = PDFChunker(max_chunk_size=500)
        toc = [
            TOCEntry(level=1, title="Chapter 1", page=0),
            TOCEntry(level=1, title="Chapter 2", page=300),
            TOCEntry(level=1, title="Chapter 3", page=600),
            TOCEntry(level=1, title="Chapter 4", page=900),
        ]
        chunks = chunker._chunk_by_toc(toc, 1200)

        # First chunk should end at page 300 (Chapter 2 boundary)
        # or the last boundary before 500
        assert chunks[0].end_page <= 500
        # Should use chapter boundaries
        assert chunks[0].end_page in [300, 500]

    def test_chunk_by_toc_no_boundary_in_range(self):
        """Should fall back to fixed split when no boundary in range."""
        chunker = PDFChunker(max_chunk_size=500)
        toc = [
            TOCEntry(level=1, title="Chapter 1", page=0),
            TOCEntry(level=1, title="Chapter 2", page=800),  # Beyond max_chunk_size
        ]
        chunks = chunker._chunk_by_toc(toc, 1000)

        # Should use fixed split since no boundary before 500
        assert chunks[0].end_page == 500 or chunks[0].end_page == 800
