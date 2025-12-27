"""
Enhanced PDF-to-markdown converter with Mistral OCR and fallback support.

This module provides a drop-in replacement for zotero-mcp's convert_to_markdown
function, using Mistral OCR for superior document understanding with automatic
fallback to markitdown if the Mistral API is unavailable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from mistral_ocr_zotero.ocr_client import MistralOCRClient, OCRResult

logger = logging.getLogger(__name__)


@dataclass
class ConversionResult:
    """Result of a PDF conversion operation."""

    markdown: str
    """The extracted markdown content."""

    source: str
    """Source of the conversion: 'mistral_ocr', 'cache', or 'markitdown'."""

    images_dir: Path | None = None
    """Directory containing extracted images, if any."""

    cached: bool = False
    """Whether the result was loaded from cache."""

    error: str | None = None
    """Error message if conversion failed but fallback succeeded."""

    images: dict[str, bytes] = field(default_factory=dict)
    """Extracted images as {filename: bytes} mapping."""

    tables: dict[str, str] = field(default_factory=dict)
    """Extracted tables as {id: content} mapping."""

    pages_processed: int = 0
    """Number of pages processed."""


@dataclass
class OCRCache:
    """
    Cache for OCR results to avoid re-processing PDFs.

    Stores results in a configurable directory with metadata for cache invalidation.
    """

    cache_dir: Path = field(default_factory=lambda: Path.home() / ".cache" / "mistral-ocr-zotero")
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_key(self, pdf_path: Path) -> str:
        """Generate a cache key based on file path and modification time."""
        stat = pdf_path.stat()
        key_data = f"{pdf_path.absolute()}:{stat.st_size}:{stat.st_mtime}"
        return hashlib.sha256(key_data.encode()).hexdigest()[:16]

    def _get_cache_path(self, cache_key: str) -> Path:
        """Get the cache directory path for a given key."""
        return self.cache_dir / cache_key

    def get(self, pdf_path: Path) -> OCRResult | None:
        """
        Retrieve cached OCR result if available and valid.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            Cached OCRResult or None if not found/invalid.
        """
        if not self.enabled:
            return None

        try:
            cache_key = self._get_cache_key(pdf_path)
            cache_path = self._get_cache_path(cache_key)

            if not cache_path.exists():
                return None

            # Load metadata
            metadata_path = cache_path / "metadata.json"
            if not metadata_path.exists():
                return None

            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)

            # Load markdown
            md_path = cache_path / "document.md"
            if not md_path.exists():
                return None

            markdown = md_path.read_text(encoding="utf-8")

            # Load images if present
            images: dict[str, bytes] = {}
            images_dir = cache_path / "images"
            if images_dir.exists():
                for img_file in images_dir.iterdir():
                    if img_file.is_file():
                        images[img_file.name] = img_file.read_bytes()

            # Load tables if present
            tables: dict[str, str] = {}
            tables_dir = cache_path / "tables"
            if tables_dir.exists():
                for tbl_file in tables_dir.glob("*.md"):
                    tables[tbl_file.name] = tbl_file.read_text(encoding="utf-8")

            logger.info(f"Cache hit for {pdf_path.name} (key: {cache_key})")

            return OCRResult(
                markdown=markdown,
                images=images,
                tables=tables,
                pages_processed=metadata.get("pages_processed", 0),
                source_file=metadata.get("source_file"),
            )

        except Exception as e:
            logger.warning(f"Failed to load from cache: {e}")
            return None

    def put(self, pdf_path: Path, result: OCRResult) -> None:
        """
        Store OCR result in cache.

        Args:
            pdf_path: Path to the original PDF file.
            result: OCRResult to cache.
        """
        if not self.enabled:
            return

        try:
            cache_key = self._get_cache_key(pdf_path)
            cache_path = self._get_cache_path(cache_key)
            cache_path.mkdir(parents=True, exist_ok=True)

            # Save markdown
            md_path = cache_path / "document.md"
            md_path.write_text(result.markdown, encoding="utf-8")

            # Save images
            if result.images:
                images_dir = cache_path / "images"
                images_dir.mkdir(exist_ok=True)
                for filename, data in result.images.items():
                    (images_dir / filename).write_bytes(data)

            # Save tables
            tables = getattr(result, 'tables', {})
            if tables:
                tables_dir = cache_path / "tables"
                tables_dir.mkdir(exist_ok=True)
                for tbl_id, content in tables.items():
                    (tables_dir / tbl_id).write_text(content, encoding="utf-8")

            # Save metadata
            metadata = {
                "source_file": result.source_file,
                "pages_processed": result.pages_processed,
                "cached_at": datetime.now().isoformat(),
                "original_path": str(pdf_path.absolute()),
            }
            metadata_path = cache_path / "metadata.json"
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)

            logger.info(f"Cached OCR result for {pdf_path.name} (key: {cache_key})")

        except Exception as e:
            logger.warning(f"Failed to cache result: {e}")


def _markitdown_fallback(file_path: Path) -> str:
    """
    Fallback conversion using markitdown library.

    Args:
        file_path: Path to the PDF file.

    Returns:
        Markdown text from markitdown.
    """
    try:
        from markitdown import MarkItDown

        md = MarkItDown()
        result = md.convert(str(file_path))
        return result.text_content
    except ImportError:
        raise ImportError(
            "markitdown is not installed. Install it with: pip install markitdown"
        )
    except Exception as e:
        return f"Error converting file with markitdown: {str(e)}"


# Global cache instance
_cache: OCRCache | None = None


def get_cache() -> OCRCache:
    """Get or create the global cache instance."""
    global _cache
    if _cache is None:
        cache_dir = os.environ.get("MISTRAL_OCR_CACHE_DIR")
        if cache_dir:
            _cache = OCRCache(cache_dir=Path(cache_dir))
        else:
            _cache = OCRCache()
    return _cache


def convert_to_markdown_enhanced(
    file_path: str | Path,
    use_cache: bool = True,
    fallback_to_markitdown: bool = True,
    mistral_api_key: str | None = None,
) -> ConversionResult:
    """
    Convert a PDF file to markdown using Mistral OCR with fallback support.

    This function is designed to be a drop-in enhancement for zotero-mcp's
    convert_to_markdown function, providing superior document understanding
    while maintaining compatibility.

    Args:
        file_path: Path to the PDF file to convert.
        use_cache: Whether to use caching for OCR results.
        fallback_to_markitdown: Whether to fall back to markitdown on API failure.
        mistral_api_key: Optional Mistral API key (uses env var if not provided).

    Returns:
        ConversionResult with markdown content and metadata.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"PDF file not found: {file_path}")

    # Check cache first
    if use_cache:
        cache = get_cache()
        cached_result = cache.get(file_path)
        if cached_result:
            return ConversionResult(
                markdown=cached_result.markdown,
                source="cache",
                images_dir=cache._get_cache_path(cache._get_cache_key(file_path)) / "images",
                cached=True,
                images=cached_result.images,
                tables=cached_result.tables,
                pages_processed=cached_result.pages_processed,
            )

    # Try Mistral OCR
    try:
        client = MistralOCRClient(api_key=mistral_api_key)
        result = client.process_pdf_from_path(file_path)

        # Cache the result
        if use_cache:
            cache = get_cache()
            cache.put(file_path, result)
            images_dir = cache._get_cache_path(cache._get_cache_key(file_path)) / "images"
        else:
            images_dir = None

        logger.info(f"Successfully processed {file_path.name} with Mistral OCR")

        return ConversionResult(
            markdown=result.markdown,
            source="mistral_ocr",
            images_dir=images_dir if result.images else None,
            cached=False,
            images=result.images,
            tables=result.tables,
            pages_processed=result.pages_processed,
        )

    except Exception as e:
        error_msg = str(e)
        logger.warning(f"Mistral OCR failed for {file_path.name}: {error_msg}")

        if not fallback_to_markitdown:
            raise

        # Fall back to markitdown
        logger.info(f"Falling back to markitdown for {file_path.name}")
        markdown = _markitdown_fallback(file_path)

        return ConversionResult(
            markdown=markdown,
            source="markitdown",
            images_dir=None,
            cached=False,
            error=f"Mistral OCR failed ({error_msg}), used markitdown fallback",
        )


def convert_to_markdown(file_path: str | Path) -> str:
    """
    Drop-in replacement for zotero-mcp's convert_to_markdown function.

    This function provides the same interface as the original but uses
    Mistral OCR with automatic fallback to markitdown.

    Args:
        file_path: Path to the file to convert.

    Returns:
        Markdown text content.
    """
    result = convert_to_markdown_enhanced(file_path)
    return result.markdown
