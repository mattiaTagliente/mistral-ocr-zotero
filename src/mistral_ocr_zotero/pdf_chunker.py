"""
PDF semantic partitioning for large document processing.

Handles the 1000-page Mistral OCR API limit by splitting PDFs at
semantic boundaries (chapters/sections) extracted from TOC/bookmarks.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
try:
    import fitz  # pymupdf
except ImportError:
    fitz = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Mistral OCR API limit (reduced from 1000 to 500 as of Jan 2026)
MAX_PAGES_PER_CHUNK = 500
# Leave margin for safety
DEFAULT_CHUNK_SIZE = 450


@dataclass
class TOCEntry:
    """Represents a table of contents entry."""

    level: int
    title: str
    page: int  # 0-indexed page number


@dataclass
class PDFChunk:
    """Represents a chunk of a PDF for processing."""

    chunk_index: int
    start_page: int  # 0-indexed, inclusive
    end_page: int  # 0-indexed, exclusive
    title: str | None = None  # Section/chapter title if from TOC
    chunk_path: Path | None = None  # Path to extracted chunk PDF

    @property
    def page_count(self) -> int:
        """Number of pages in this chunk."""
        return self.end_page - self.start_page


@dataclass
class ChunkingResult:
    """Result of PDF analysis and chunking."""

    original_path: Path
    total_pages: int
    chunks: list[PDFChunk]
    has_toc: bool
    temp_dir: Path | None = None  # Cleanup responsibility

    @property
    def needs_chunking(self) -> bool:
        """Whether the PDF exceeds the API limit."""
        return self.total_pages > MAX_PAGES_PER_CHUNK


class PDFChunker:
    """
    Analyzes and splits PDFs for processing within API limits.

    Uses document TOC/bookmarks to find semantic split points,
    falling back to fixed-size chunking when no TOC is available.
    """

    def __init__(
        self,
        max_chunk_size: int = DEFAULT_CHUNK_SIZE,
        min_chapter_level: int = 1,
        max_chapter_level: int = 2,
    ) -> None:
        """
        Initialize the PDF chunker.

        Args:
            max_chunk_size: maximum pages per chunk (default 950).
            min_chapter_level: minimum TOC level to consider for splits (1 = top level).
            max_chapter_level: maximum TOC level for split points.
        """
        self.max_chunk_size = max_chunk_size
        self.min_chapter_level = min_chapter_level
        self.max_chapter_level = max_chapter_level

    def analyze(self, pdf_path: Path) -> ChunkingResult:
        """
        Analyze a PDF and determine chunking strategy.

        Args:
            pdf_path: path to the PDF file.

        Returns:
            ChunkingResult with chunk definitions.
        """
        if fitz is None:
            raise ImportError("pymupdf is required for PDF chunking")

        doc = fitz.open(pdf_path)
        total_pages = len(doc)

        # Extract TOC
        toc = self._extract_toc(doc)
        has_toc = len(toc) > 0

        if total_pages <= MAX_PAGES_PER_CHUNK:
            # No chunking needed
            chunks = [
                PDFChunk(
                    chunk_index=0,
                    start_page=0,
                    end_page=total_pages,
                    title=None,
                )
            ]
            doc.close()
            return ChunkingResult(
                original_path=pdf_path,
                total_pages=total_pages,
                chunks=chunks,
                has_toc=has_toc,
            )

        # Determine chunk boundaries
        if has_toc:
            chunks = self._chunk_by_toc(toc, total_pages)
        else:
            chunks = self._chunk_by_size(total_pages)

        doc.close()

        logger.info(
            f"PDF analysis: {total_pages} pages, {len(chunks)} chunks, "
            f"TOC {'available' if has_toc else 'not available'}"
        )

        return ChunkingResult(
            original_path=pdf_path,
            total_pages=total_pages,
            chunks=chunks,
            has_toc=has_toc,
        )

    def extract_chunks(
        self,
        pdf_path: Path,
        chunks: list[PDFChunk],
        output_dir: Path | None = None,
    ) -> list[PDFChunk]:
        """
        Extract chunk PDFs from the original document.

        Args:
            pdf_path: path to original PDF.
            chunks: chunk definitions from analyze().
            output_dir: directory for chunk files (uses temp if None).

        Returns:
            Updated chunks with chunk_path set.
        """
        if fitz is None:
            raise ImportError("pymupdf is required for PDF chunking")

        if output_dir is None:
            output_dir = Path(tempfile.mkdtemp(prefix="pdf_chunks_"))

        doc = fitz.open(pdf_path)

        for chunk in chunks:
            chunk_doc = fitz.open()  # New empty document
            chunk_doc.insert_pdf(
                doc,
                from_page=chunk.start_page,
                to_page=chunk.end_page - 1,  # insert_pdf uses inclusive end
            )

            chunk_filename = f"chunk_{chunk.chunk_index:03d}.pdf"
            chunk_path = output_dir / chunk_filename
            chunk_doc.save(str(chunk_path))
            chunk_doc.close()

            chunk.chunk_path = chunk_path
            logger.info(
                f"Extracted chunk {chunk.chunk_index}: "
                f"pages {chunk.start_page + 1}-{chunk.end_page} -> {chunk_path.name}"
            )

        doc.close()
        return chunks

    def _extract_toc(self, doc: "fitz.Document") -> list[TOCEntry]:
        """Extract and parse document TOC."""
        raw_toc = doc.get_toc()
        entries = []

        for item in raw_toc:
            level, title, page = item[0], item[1], item[2]
            # Filter by configured levels
            if self.min_chapter_level <= level <= self.max_chapter_level:
                # Validate page number
                if 1 <= page <= len(doc):
                    entries.append(
                        TOCEntry(
                            level=level,
                            title=title,
                            page=page - 1,  # Convert to 0-indexed
                        )
                    )

        logger.debug(f"Extracted {len(entries)} TOC entries (levels {self.min_chapter_level}-{self.max_chapter_level})")
        return entries

    def _chunk_by_toc(
        self,
        toc: list[TOCEntry],
        total_pages: int,
    ) -> list[PDFChunk]:
        """
        Create chunks based on TOC boundaries.

        Strategy: find the last chapter boundary before each 1000-page limit.
        """
        chunks = []
        current_start = 0
        chunk_index = 0

        # Sort TOC entries by page
        sorted_toc = sorted(toc, key=lambda e: e.page)

        while current_start < total_pages:
            # Find the furthest we can go
            max_end = min(current_start + self.max_chunk_size, total_pages)

            if max_end >= total_pages:
                # Last chunk - take everything remaining
                chunks.append(
                    PDFChunk(
                        chunk_index=chunk_index,
                        start_page=current_start,
                        end_page=total_pages,
                        title=self._get_section_title(sorted_toc, current_start),
                    )
                )
                break

            # Find last TOC entry before max_end that's after current_start
            best_split = None
            for entry in sorted_toc:
                if current_start < entry.page <= max_end:
                    best_split = entry.page

            if best_split is None:
                # No TOC boundary found - use fixed split
                # But check if remaining pages fit
                if total_pages - current_start <= self.max_chunk_size:
                    best_split = total_pages
                else:
                    best_split = max_end
                    logger.warning(
                        f"No TOC boundary in pages {current_start + 1}-{max_end}, "
                        f"using fixed split at page {best_split}"
                    )

            chunks.append(
                PDFChunk(
                    chunk_index=chunk_index,
                    start_page=current_start,
                    end_page=best_split,
                    title=self._get_section_title(sorted_toc, current_start),
                )
            )

            current_start = best_split
            chunk_index += 1

        return chunks

    def _chunk_by_size(self, total_pages: int) -> list[PDFChunk]:
        """Create fixed-size chunks when no TOC is available."""
        chunks = []
        chunk_index = 0
        current_start = 0

        while current_start < total_pages:
            end_page = min(current_start + self.max_chunk_size, total_pages)
            chunks.append(
                PDFChunk(
                    chunk_index=chunk_index,
                    start_page=current_start,
                    end_page=end_page,
                    title=None,
                )
            )
            current_start = end_page
            chunk_index += 1

        return chunks

    def _get_section_title(
        self,
        toc: list[TOCEntry],
        page: int,
    ) -> str | None:
        """Get the section title for a given page."""
        best_match = None
        for entry in toc:
            if entry.page <= page:
                best_match = entry.title
            else:
                break
        return best_match
