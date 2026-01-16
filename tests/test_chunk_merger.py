"""Tests for chunk merging functionality."""

import pytest

from mistral_ocr_zotero.ocr_client import OCRResult
from mistral_ocr_zotero.pdf_chunker import PDFChunk
from mistral_ocr_zotero.chunk_merger import ChunkMerger, ChunkOCRResult


class TestChunkOCRResult:
    """Tests for ChunkOCRResult dataclass."""

    def test_chunk_ocr_result_creation(self):
        """ChunkOCRResult should store chunk and result."""
        chunk = PDFChunk(chunk_index=0, start_page=0, end_page=100)
        result = OCRResult(
            markdown="# Test",
            images={},
            tables={},
            pages_processed=100,
        )
        chunk_result = ChunkOCRResult(chunk=chunk, result=result)

        assert chunk_result.chunk == chunk
        assert chunk_result.result == result


class TestChunkMerger:
    """Tests for ChunkMerger class."""

    def test_single_chunk_passthrough(self):
        """Single chunk should return original result."""
        chunk = PDFChunk(chunk_index=0, start_page=0, end_page=100)
        result = OCRResult(
            markdown="# Test\n\n<!-- Page 1 -->\nContent",
            images={"img-001.jpeg": b"image_data"},
            tables={"tbl-001": "| A | B |"},
            pages_processed=100,
            source_file="test.pdf",
        )
        chunk_results = [ChunkOCRResult(chunk=chunk, result=result)]

        merger = ChunkMerger()
        merged = merger.merge(chunk_results)

        assert merged.markdown == result.markdown
        assert merged.images == result.images
        assert merged.tables == result.tables
        assert merged.pages_processed == 100

    def test_single_chunk_with_source_file_override(self):
        """Single chunk should use provided source_file."""
        chunk = PDFChunk(chunk_index=0, start_page=0, end_page=100)
        result = OCRResult(
            markdown="# Test",
            images={},
            tables={},
            pages_processed=100,
            source_file="original.pdf",
        )
        chunk_results = [ChunkOCRResult(chunk=chunk, result=result)]

        merger = ChunkMerger()
        merged = merger.merge(chunk_results, source_file="new_name.pdf")

        assert merged.source_file == "new_name.pdf"

    def test_two_chunks_page_renumbering(self):
        """Page markers should be renumbered correctly across chunks."""
        chunks = [
            ChunkOCRResult(
                chunk=PDFChunk(chunk_index=0, start_page=0, end_page=100),
                result=OCRResult(
                    markdown="<!-- Page 1 -->\nChunk 1 content\n<!-- Page 50 -->\nMore content",
                    images={},
                    tables={},
                    pages_processed=100,
                ),
            ),
            ChunkOCRResult(
                chunk=PDFChunk(chunk_index=1, start_page=100, end_page=200),
                result=OCRResult(
                    markdown="<!-- Page 1 -->\nChunk 2 content\n<!-- Page 50 -->\nMore content",
                    images={},
                    tables={},
                    pages_processed=100,
                ),
            ),
        ]

        merger = ChunkMerger()
        merged = merger.merge(chunks)

        # First chunk pages stay the same (offset 0)
        assert "<!-- Page 1 -->" in merged.markdown
        assert "<!-- Page 50 -->" in merged.markdown
        # Second chunk's Page 1 should become Page 101 (offset 100)
        assert "<!-- Page 101 -->" in merged.markdown
        # Second chunk's Page 50 should become Page 150
        assert "<!-- Page 150 -->" in merged.markdown
        # Total pages
        assert merged.pages_processed == 200

    def test_image_prefixing_avoids_collisions(self):
        """Images from different chunks should have unique names."""
        chunks = [
            ChunkOCRResult(
                chunk=PDFChunk(chunk_index=0, start_page=0, end_page=100),
                result=OCRResult(
                    markdown="![](img-001.jpeg)",
                    images={"img-001.jpeg": b"data1"},
                    tables={},
                    pages_processed=100,
                ),
            ),
            ChunkOCRResult(
                chunk=PDFChunk(chunk_index=1, start_page=100, end_page=200),
                result=OCRResult(
                    markdown="![](img-001.jpeg)",
                    images={"img-001.jpeg": b"data2"},
                    tables={},
                    pages_processed=100,
                ),
            ),
        ]

        merger = ChunkMerger()
        merged = merger.merge(chunks)

        # Should have two distinct images with chunk prefixes
        assert "chunk00_img-001.jpeg" in merged.images
        assert "chunk01_img-001.jpeg" in merged.images
        assert merged.images["chunk00_img-001.jpeg"] == b"data1"
        assert merged.images["chunk01_img-001.jpeg"] == b"data2"

    def test_table_prefixing(self):
        """Tables from different chunks should have unique IDs."""
        chunks = [
            ChunkOCRResult(
                chunk=PDFChunk(chunk_index=0, start_page=0, end_page=100),
                result=OCRResult(
                    markdown="See [tbl-001]",
                    images={},
                    tables={"tbl-001": "| A | B |"},
                    pages_processed=100,
                ),
            ),
            ChunkOCRResult(
                chunk=PDFChunk(chunk_index=1, start_page=100, end_page=200),
                result=OCRResult(
                    markdown="See [tbl-001]",
                    images={},
                    tables={"tbl-001": "| C | D |"},
                    pages_processed=100,
                ),
            ),
        ]

        merger = ChunkMerger()
        merged = merger.merge(chunks)

        # Should have two distinct tables with chunk prefixes
        assert "chunk00_tbl-001" in merged.tables
        assert "chunk01_tbl-001" in merged.tables

    def test_provenance_markers(self):
        """Merged markdown should include chunk provenance markers."""
        chunks = [
            ChunkOCRResult(
                chunk=PDFChunk(
                    chunk_index=0, start_page=0, end_page=100, title="Introduction"
                ),
                result=OCRResult(
                    markdown="Content 1",
                    images={},
                    tables={},
                    pages_processed=100,
                ),
            ),
            ChunkOCRResult(
                chunk=PDFChunk(
                    chunk_index=1, start_page=100, end_page=200, title="Methods"
                ),
                result=OCRResult(
                    markdown="Content 2",
                    images={},
                    tables={},
                    pages_processed=100,
                ),
            ),
        ]

        merger = ChunkMerger()
        merged = merger.merge(chunks)

        # Should have header indicating merged document
        assert "Merged from 2 chunks" in merged.markdown
        # Should have chunk markers
        assert "Chunk 1 of 2" in merged.markdown
        assert "Chunk 2 of 2" in merged.markdown
        # Should include page ranges
        assert "pages 1-100" in merged.markdown
        assert "pages 101-200" in merged.markdown
        # Should include section titles
        assert "Section: Introduction" in merged.markdown
        assert "Section: Methods" in merged.markdown

    def test_image_path_with_images_prefix(self):
        """Image references with images/ prefix should be updated correctly."""
        chunks = [
            ChunkOCRResult(
                chunk=PDFChunk(chunk_index=0, start_page=0, end_page=100),
                result=OCRResult(
                    markdown="![Alt](images/img-001.jpeg)",
                    images={"img-001.jpeg": b"data"},
                    tables={},
                    pages_processed=100,
                ),
            ),
        ]

        merger = ChunkMerger()
        merged = merger.merge(chunks, source_file="test.pdf")

        # For single chunk, passthrough without modification
        assert "images/img-001.jpeg" in merged.markdown

    def test_multiple_chunks_image_path_update(self):
        """Multi-chunk merge should update image paths in markdown."""
        chunks = [
            ChunkOCRResult(
                chunk=PDFChunk(chunk_index=0, start_page=0, end_page=100),
                result=OCRResult(
                    markdown="![Alt](images/img-001.jpeg)\n![Alt2](img-002.png)",
                    images={"img-001.jpeg": b"data1", "img-002.png": b"data2"},
                    tables={},
                    pages_processed=100,
                ),
            ),
            ChunkOCRResult(
                chunk=PDFChunk(chunk_index=1, start_page=100, end_page=200),
                result=OCRResult(
                    markdown="![Alt](img-001.jpeg)",
                    images={"img-001.jpeg": b"data3"},
                    tables={},
                    pages_processed=100,
                ),
            ),
        ]

        merger = ChunkMerger()
        merged = merger.merge(chunks)

        # Image references should be prefixed
        assert "chunk00_img-001.jpeg" in merged.markdown
        assert "chunk00_img-002.png" in merged.markdown
        assert "chunk01_img-001.jpeg" in merged.markdown


class TestChunkMergerEdgeCases:
    """Edge case tests for ChunkMerger."""

    def test_empty_images_and_tables(self):
        """Merging chunks with no images or tables should work."""
        chunks = [
            ChunkOCRResult(
                chunk=PDFChunk(chunk_index=0, start_page=0, end_page=100),
                result=OCRResult(
                    markdown="Text only",
                    images={},
                    tables={},
                    pages_processed=100,
                ),
            ),
            ChunkOCRResult(
                chunk=PDFChunk(chunk_index=1, start_page=100, end_page=200),
                result=OCRResult(
                    markdown="More text",
                    images={},
                    tables={},
                    pages_processed=100,
                ),
            ),
        ]

        merger = ChunkMerger()
        merged = merger.merge(chunks)

        assert merged.pages_processed == 200
        assert len(merged.images) == 0
        assert len(merged.tables) == 0

    def test_three_chunks(self):
        """Merging three chunks should work correctly."""
        chunks = [
            ChunkOCRResult(
                chunk=PDFChunk(chunk_index=0, start_page=0, end_page=100),
                result=OCRResult(
                    markdown="<!-- Page 1 -->\nA",
                    images={"img-001.jpeg": b"a"},
                    tables={},
                    pages_processed=100,
                ),
            ),
            ChunkOCRResult(
                chunk=PDFChunk(chunk_index=1, start_page=100, end_page=200),
                result=OCRResult(
                    markdown="<!-- Page 1 -->\nB",
                    images={"img-001.jpeg": b"b"},
                    tables={},
                    pages_processed=100,
                ),
            ),
            ChunkOCRResult(
                chunk=PDFChunk(chunk_index=2, start_page=200, end_page=300),
                result=OCRResult(
                    markdown="<!-- Page 1 -->\nC",
                    images={"img-001.jpeg": b"c"},
                    tables={},
                    pages_processed=100,
                ),
            ),
        ]

        merger = ChunkMerger()
        merged = merger.merge(chunks)

        assert merged.pages_processed == 300
        # Should have 3 images with different prefixes
        assert "chunk00_img-001.jpeg" in merged.images
        assert "chunk01_img-001.jpeg" in merged.images
        assert "chunk02_img-001.jpeg" in merged.images
        # Page numbers: chunk 0 stays 1, chunk 1 becomes 101, chunk 2 becomes 201
        assert "<!-- Page 1 -->" in merged.markdown
        assert "<!-- Page 101 -->" in merged.markdown
        assert "<!-- Page 201 -->" in merged.markdown
