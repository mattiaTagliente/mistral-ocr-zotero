"""
Mistral OCR API client for PDF-to-markdown conversion.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from mistralai import Mistral
from mistralai.models import DocumentURLChunk

logger = logging.getLogger(__name__)

# Retry configuration for transient API errors
MAX_RETRIES = 5
RETRY_DELAY_SECONDS = 10

if TYPE_CHECKING:
    from mistralai.models import OCRResponse


@dataclass
class OCRResult:
    """Result of OCR processing for a document."""

    markdown: str
    """Combined markdown content from all pages."""

    images: dict[str, bytes]
    """Extracted images as {filename: bytes} mapping."""

    pages_processed: int
    """Number of pages processed."""

    source_file: str | None = None
    """Original source file name if available."""

    tables: dict[str, str] = field(default_factory=dict)
    """Extracted tables as {id: content} mapping."""


@dataclass
class MistralOCRClient:
    """Client for Mistral OCR API operations."""

    api_key: str | None = field(default=None, repr=False)
    model: str = "mistral-ocr-latest"
    _client: Mistral | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.environ.get("MISTRAL_API_KEY")
        if not self.api_key:
            raise ValueError(
                "MISTRAL_API_KEY must be provided or set in environment variables"
            )
        self._client = Mistral(api_key=self.api_key)

    @property
    def client(self) -> Mistral:
        """Get the Mistral client instance."""
        if self._client is None:
            raise RuntimeError("Client not initialized")
        return self._client

    def process_pdf_from_path(
        self,
        pdf_path: Path | str,
        include_images: bool = True,
        table_format: str = "markdown",
    ) -> OCRResult:
        """
        Process a local PDF file through Mistral OCR.

        Args:
            pdf_path: Path to the PDF file.
            include_images: Whether to extract embedded images.
            table_format: Format for tables ("markdown" or "html").

        Returns:
            OCRResult with extracted markdown and images.
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        # Upload file to Mistral
        uploaded_file = self.client.files.upload(
            file={
                "file_name": pdf_path.name,
                "content": pdf_path.read_bytes(),
            },
            purpose="ocr",
        )

        # Process with OCR (with retry for transient errors)
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                # Get fresh signed URL for each attempt (URLs expire after 1 minute)
                signed_url = self.client.files.get_signed_url(
                    file_id=uploaded_file.id, expiry=1
                )
                response = self.client.ocr.process(
                    document=DocumentURLChunk(document_url=signed_url.url),
                    model=self.model,
                    include_image_base64=include_images,
                    table_format=table_format,  # type: ignore[arg-type]
                )
                return self._parse_response(response, source_file=pdf_path.name)
            except Exception as e:
                last_error = e
                error_str = str(e)
                # Retry on 500/503 errors (transient server issues)
                if "500" in error_str or "503" in error_str or "Service unavailable" in error_str:
                    if attempt < MAX_RETRIES - 1:
                        wait_time = RETRY_DELAY_SECONDS * (attempt + 1)
                        logger.warning(
                            f"OCR request failed with transient error (attempt {attempt + 1}/{MAX_RETRIES}), "
                            f"retrying in {wait_time}s: {e}"
                        )
                        time.sleep(wait_time)
                        continue
                # Non-retryable error, raise immediately
                raise

        # All retries exhausted
        raise last_error  # type: ignore[misc]

    def process_pdf_from_url(
        self,
        url: str,
        include_images: bool = True,
        table_format: str = "markdown",
    ) -> OCRResult:
        """
        Process a PDF from a URL through Mistral OCR.

        Args:
            url: URL of the PDF document.
            include_images: Whether to extract embedded images.
            table_format: Format for tables ("markdown" or "html").

        Returns:
            OCRResult with extracted markdown and images.
        """
        response = self.client.ocr.process(
            model=self.model,
            document={
                "type": "document_url",
                "document_url": url,
            },
            include_image_base64=include_images,
            table_format=table_format,  # type: ignore[arg-type]
        )

        return self._parse_response(response)

    def _parse_response(
        self, response: OCRResponse, source_file: str | None = None
    ) -> OCRResult:
        """Parse OCR response into structured result."""
        markdown_parts: list[str] = []
        images: dict[str, bytes] = {}
        tables: dict[str, str] = {}
        image_counter = 0

        for page in response.pages:
            # Add page separator for multi-page documents
            if page.index > 0:
                markdown_parts.append(f"\n\n---\n<!-- Page {page.index + 1} -->\n\n")

            markdown_parts.append(page.markdown)

            # Extract images if available
            if hasattr(page, "images") and page.images:
                for img in page.images:
                    if hasattr(img, "image_base64") and img.image_base64:
                        image_counter += 1
                        # Use the image's id as filename (matches markdown references)
                        filename = img.id if hasattr(img, "id") and img.id else f"image_{page.index:03d}_{image_counter:03d}.png"
                        image_data = base64.b64decode(img.image_base64)

                        # Fix corrupted image headers - find actual image start
                        # JPEG starts with FF D8, PNG starts with 89 50 4E 47
                        jpeg_soi = image_data.find(b'\xff\xd8')
                        png_sig = image_data.find(b'\x89PNG')

                        if jpeg_soi > 0 and (png_sig < 0 or jpeg_soi < png_sig):
                            image_data = image_data[jpeg_soi:]
                        elif png_sig > 0:
                            image_data = image_data[png_sig:]

                        images[filename] = image_data

            # Extract tables if available
            if hasattr(page, "tables") and page.tables:
                for tbl in page.tables:
                    if hasattr(tbl, "id") and hasattr(tbl, "content"):
                        tables[tbl.id] = tbl.content

        return OCRResult(
            markdown="\n".join(markdown_parts),
            images=images,
            tables=tables,
            pages_processed=response.usage_info.pages_processed,
            source_file=source_file,
        )

    def save_result(
        self,
        result: OCRResult,
        output_dir: Path | str,
        markdown_filename: str = "document.md",
    ) -> Path:
        """
        Save OCR result to disk.

        Args:
            result: OCR result to save.
            output_dir: Directory to save output.
            markdown_filename: Name for the markdown file.

        Returns:
            Path to the output directory.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save markdown
        md_path = output_dir / markdown_filename
        md_path.write_text(result.markdown, encoding="utf-8")

        # Save images in subdirectory
        if result.images:
            images_dir = output_dir / "images"
            images_dir.mkdir(exist_ok=True)
            for filename, data in result.images.items():
                (images_dir / filename).write_bytes(data)

        return output_dir
