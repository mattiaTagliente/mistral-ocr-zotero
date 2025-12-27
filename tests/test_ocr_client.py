"""Tests for the Mistral OCR client."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from mistral_ocr_zotero.ocr_client import MistralOCRClient, OCRResult


class TestMistralOCRClient:
    """Tests for MistralOCRClient."""

    def test_init_with_api_key(self) -> None:
        """Test client initialization with explicit API key."""
        with patch("mistral_ocr_zotero.ocr_client.Mistral"):
            client = MistralOCRClient(api_key="test-key")
            assert client.api_key == "test-key"
            assert client.model == "mistral-ocr-latest"

    def test_init_from_env(self) -> None:
        """Test client initialization from environment variable."""
        with patch.dict(os.environ, {"MISTRAL_API_KEY": "env-key"}):
            with patch("mistral_ocr_zotero.ocr_client.Mistral"):
                client = MistralOCRClient()
                assert client.api_key == "env-key"

    def test_init_no_key_raises(self) -> None:
        """Test that missing API key raises ValueError."""
        with patch.dict(os.environ, {}, clear=True):
            # Ensure MISTRAL_API_KEY is not set
            os.environ.pop("MISTRAL_API_KEY", None)
            with pytest.raises(ValueError, match="MISTRAL_API_KEY"):
                MistralOCRClient()

    def test_process_pdf_file_not_found(self) -> None:
        """Test that processing non-existent file raises FileNotFoundError."""
        with patch("mistral_ocr_zotero.ocr_client.Mistral"):
            client = MistralOCRClient(api_key="test-key")
            with pytest.raises(FileNotFoundError):
                client.process_pdf_from_path("/nonexistent/file.pdf")


class TestOCRResult:
    """Tests for OCRResult dataclass."""

    def test_ocr_result_creation(self) -> None:
        """Test OCRResult can be created with required fields."""
        result = OCRResult(
            markdown="# Test\n\nContent",
            images={"img_001.png": b"fake-image-data"},
            pages_processed=1,
            source_file="test.pdf",
        )
        assert result.markdown == "# Test\n\nContent"
        assert len(result.images) == 1
        assert result.pages_processed == 1
        assert result.source_file == "test.pdf"

    def test_ocr_result_optional_source(self) -> None:
        """Test OCRResult with optional source_file."""
        result = OCRResult(
            markdown="Content",
            images={},
            pages_processed=1,
        )
        assert result.source_file is None
