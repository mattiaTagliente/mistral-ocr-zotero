"""Tests for the converter module."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mistral_ocr_zotero.converter import (
    OCRCache,
    ConversionResult,
    convert_to_markdown,
    convert_to_markdown_enhanced,
)
from mistral_ocr_zotero.ocr_client import OCRResult


class TestOCRCache:
    """Tests for OCRCache."""

    def test_cache_disabled(self) -> None:
        """Test that disabled cache returns None."""
        cache = OCRCache(enabled=False)
        result = cache.get(Path("/fake/path.pdf"))
        assert result is None

    def test_cache_miss(self) -> None:
        """Test cache miss for non-existent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = OCRCache(cache_dir=Path(tmpdir), enabled=True)
            result = cache.get(Path("/nonexistent/file.pdf"))
            assert result is None

    def test_cache_put_and_get(self) -> None:
        """Test caching and retrieving results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            pdf_dir = Path(tmpdir) / "pdfs"
            pdf_dir.mkdir()

            # Create a fake PDF file
            pdf_path = pdf_dir / "test.pdf"
            pdf_path.write_bytes(b"fake pdf content")

            cache = OCRCache(cache_dir=cache_dir, enabled=True)

            # Create and cache a result
            result = OCRResult(
                markdown="# Test Document\n\nContent here.",
                images={"img_001.png": b"fake image data"},
                pages_processed=1,
                source_file="test.pdf",
            )

            cache.put(pdf_path, result)

            # Retrieve from cache
            cached = cache.get(pdf_path)
            assert cached is not None
            assert cached.markdown == result.markdown
            assert cached.pages_processed == result.pages_processed
            assert "img_001.png" in cached.images


class TestConvertToMarkdownEnhanced:
    """Tests for convert_to_markdown_enhanced."""

    def test_file_not_found(self) -> None:
        """Test that FileNotFoundError is raised for missing files."""
        with pytest.raises(FileNotFoundError):
            convert_to_markdown_enhanced("/nonexistent/file.pdf")

    @patch("mistral_ocr_zotero.converter.MistralOCRClient")
    def test_mistral_ocr_success(self, mock_client_class: MagicMock) -> None:
        """Test successful Mistral OCR conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fake PDF file
            pdf_path = Path(tmpdir) / "test.pdf"
            pdf_path.write_bytes(b"fake pdf content")

            # Mock the OCR client
            mock_client = MagicMock()
            mock_result = OCRResult(
                markdown="# OCR Result\n\nExtracted content.",
                images={},
                pages_processed=1,
                source_file="test.pdf",
            )
            mock_client.process_pdf_from_path.return_value = mock_result
            mock_client_class.return_value = mock_client

            result = convert_to_markdown_enhanced(
                pdf_path,
                use_cache=False,
                mistral_api_key="test-key",
            )

            assert result.source == "mistral_ocr"
            assert result.markdown == "# OCR Result\n\nExtracted content."
            assert not result.cached

    @patch("mistral_ocr_zotero.converter.MistralOCRClient")
    @patch("mistral_ocr_zotero.converter._markitdown_fallback")
    def test_fallback_to_markitdown(
        self, mock_markitdown: MagicMock, mock_client_class: MagicMock
    ) -> None:
        """Test fallback to markitdown when Mistral OCR fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fake PDF file
            pdf_path = Path(tmpdir) / "test.pdf"
            pdf_path.write_bytes(b"fake pdf content")

            # Mock OCR failure
            mock_client = MagicMock()
            mock_client.process_pdf_from_path.side_effect = Exception("API error")
            mock_client_class.return_value = mock_client

            # Mock markitdown success
            mock_markitdown.return_value = "# Markitdown Result\n\nFallback content."

            result = convert_to_markdown_enhanced(
                pdf_path,
                use_cache=False,
                fallback_to_markitdown=True,
                mistral_api_key="test-key",
            )

            assert result.source == "markitdown"
            assert "Markitdown Result" in result.markdown
            assert result.error is not None
            assert "API error" in result.error


class TestConvertToMarkdown:
    """Tests for the drop-in convert_to_markdown function."""

    @patch("mistral_ocr_zotero.converter.convert_to_markdown_enhanced")
    def test_returns_markdown_string(self, mock_enhanced: MagicMock) -> None:
        """Test that convert_to_markdown returns a string."""
        mock_enhanced.return_value = ConversionResult(
            markdown="# Test",
            source="mistral_ocr",
        )

        result = convert_to_markdown("/fake/path.pdf")

        assert isinstance(result, str)
        assert result == "# Test"
