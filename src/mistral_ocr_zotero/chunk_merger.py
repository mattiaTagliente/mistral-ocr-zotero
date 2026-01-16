"""
Merge OCR results from multiple PDF chunks into unified output.

Handles page renumbering, image/table renaming, and provenance tracking.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from mistral_ocr_zotero.ocr_client import OCRResult
from mistral_ocr_zotero.pdf_chunker import PDFChunk

logger = logging.getLogger(__name__)


@dataclass
class ChunkOCRResult:
    """OCR result with chunk context."""

    chunk: PDFChunk
    result: OCRResult


class ChunkMerger:
    """
    Merges OCR results from multiple PDF chunks.

    Handles:
    - Continuous page numbering across chunks
    - Image/table name prefixing to avoid collisions
    - Provenance tracking for debugging
    """

    def merge(
        self,
        chunk_results: list[ChunkOCRResult],
        source_file: str | None = None,
    ) -> OCRResult:
        """
        Merge multiple chunk results into a single OCRResult.

        Args:
            chunk_results: list of chunk results in order.
            source_file: original source filename.

        Returns:
            Unified OCRResult with merged content.
        """
        if len(chunk_results) == 1:
            # Single chunk - return as-is (but update source_file if needed)
            result = chunk_results[0].result
            if source_file:
                return OCRResult(
                    markdown=result.markdown,
                    images=result.images,
                    tables=result.tables,
                    pages_processed=result.pages_processed,
                    source_file=source_file,
                )
            return result

        merged_markdown_parts = []
        merged_images: dict[str, bytes] = {}
        merged_tables: dict[str, str] = {}
        total_pages = 0

        # Track running page offset for renumbering
        page_offset = 0

        # Add header indicating merged document
        merged_markdown_parts.append(
            f"<!-- Merged from {len(chunk_results)} chunks -->\n"
        )

        for chunk_result in chunk_results:
            chunk = chunk_result.chunk
            result = chunk_result.result
            chunk_prefix = f"chunk{chunk.chunk_index:02d}_"

            # Add chunk separator/provenance marker
            chunk_header = (
                f"\n\n<!-- Chunk {chunk.chunk_index + 1} of {len(chunk_results)} "
                f"(original pages {chunk.start_page + 1}-{chunk.end_page}) -->\n"
            )
            if chunk.title:
                chunk_header += f"<!-- Section: {chunk.title} -->\n"

            merged_markdown_parts.append(chunk_header)

            # Process markdown: renumber pages and update references
            processed_md = self._process_markdown(
                result.markdown,
                page_offset=page_offset,
                chunk_prefix=chunk_prefix,
            )
            merged_markdown_parts.append(processed_md)

            # Merge images with prefixed names
            for img_name, img_data in result.images.items():
                new_name = chunk_prefix + img_name
                merged_images[new_name] = img_data

            # Merge tables with prefixed names
            for tbl_id, tbl_content in result.tables.items():
                new_id = chunk_prefix + tbl_id
                merged_tables[new_id] = tbl_content

            page_offset += result.pages_processed
            total_pages += result.pages_processed

        # Construct final markdown
        final_markdown = "".join(merged_markdown_parts)

        logger.info(
            f"Merged {len(chunk_results)} chunks: "
            f"{total_pages} pages, {len(merged_images)} images, "
            f"{len(merged_tables)} tables"
        )

        return OCRResult(
            markdown=final_markdown,
            images=merged_images,
            tables=merged_tables,
            pages_processed=total_pages,
            source_file=source_file,
        )

    def _process_markdown(
        self,
        markdown: str,
        page_offset: int,
        chunk_prefix: str,
    ) -> str:
        """
        Process markdown to update page numbers and references.

        Args:
            markdown: original chunk markdown.
            page_offset: number of pages in previous chunks.
            chunk_prefix: prefix for image/table references.

        Returns:
            Processed markdown with updated references.
        """
        processed = markdown

        # Update page markers: <!-- Page N --> to reflect actual position
        def replace_page_marker(match: re.Match) -> str:
            page_num = int(match.group(1))
            new_page = page_num + page_offset
            return f"<!-- Page {new_page} -->"

        processed = re.sub(
            r"<!-- Page (\d+) -->",
            replace_page_marker,
            processed,
        )

        # Update image references in markdown syntax: ![...](img-N.ext)
        # Also handle paths like images/img-N.ext
        processed = re.sub(
            r"\]\(((?:images/)?)(img-\d+\.[a-z]+)\)",
            lambda m: f"]({m.group(1)}{chunk_prefix}{m.group(2)})",
            processed,
        )

        # Update image references in HTML img tags
        processed = re.sub(
            r'src="((?:images/)?)(img-\d+\.[a-z]+)"',
            lambda m: f'src="{m.group(1)}{chunk_prefix}{m.group(2)}"',
            processed,
        )

        # Update table references if they appear in markdown
        processed = re.sub(
            r"\[(tbl-\d+)\]",
            lambda m: f"[{chunk_prefix}{m.group(1)}]",
            processed,
        )

        return processed
