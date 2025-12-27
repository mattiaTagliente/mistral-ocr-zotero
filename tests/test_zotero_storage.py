"""Tests for the Zotero storage module."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mistral_ocr_zotero.ocr_client import OCRResult


class TestZoteroOCRStorage:
    """Tests for ZoteroOCRStorage."""

    @patch("mistral_ocr_zotero.zotero_storage.zotero.Zotero")
    def test_init_from_env(self, mock_zotero: MagicMock) -> None:
        """Test initialization from environment variables."""
        with patch.dict(
            os.environ,
            {
                "ZOTERO_LIBRARY_ID": "12345",
                "ZOTERO_API_KEY": "test-api-key",
            },
        ):
            from mistral_ocr_zotero.zotero_storage import ZoteroOCRStorage

            storage = ZoteroOCRStorage()
            assert storage.library_id == "12345"
            mock_zotero.assert_called_once()

    def test_init_missing_credentials(self) -> None:
        """Test that missing credentials raise ValueError."""
        # Don't clear HOME/USERPROFILE as it breaks Path.home()
        env_without_zotero = {
            k: v for k, v in os.environ.items()
            if not k.startswith("ZOTERO_")
        }
        with patch.dict(os.environ, env_without_zotero, clear=True):
            from mistral_ocr_zotero.zotero_storage import ZoteroOCRStorage

            with pytest.raises(ValueError, match="ZOTERO_LIBRARY_ID"):
                ZoteroOCRStorage()

    @patch("mistral_ocr_zotero.zotero_storage.zotero.Zotero")
    def test_has_ocr_conversion_false(self, mock_zotero: MagicMock) -> None:
        """Test has_ocr_conversion returns False when no OCR attachment exists."""
        with patch.dict(
            os.environ,
            {
                "ZOTERO_LIBRARY_ID": "12345",
                "ZOTERO_API_KEY": "test-api-key",
            },
        ):
            from mistral_ocr_zotero.zotero_storage import ZoteroOCRStorage

            mock_zot_instance = MagicMock()
            mock_zot_instance.children.return_value = [
                {"data": {"itemType": "attachment", "title": "Document.pdf"}}
            ]
            mock_zotero.return_value = mock_zot_instance

            storage = ZoteroOCRStorage()
            assert not storage.has_ocr_conversion("ABC123")

    @patch("mistral_ocr_zotero.zotero_storage.zotero.Zotero")
    def test_has_ocr_conversion_true(self, mock_zotero: MagicMock) -> None:
        """Test has_ocr_conversion returns True when OCR attachment exists."""
        with patch.dict(
            os.environ,
            {
                "ZOTERO_LIBRARY_ID": "12345",
                "ZOTERO_API_KEY": "test-api-key",
            },
        ):
            from mistral_ocr_zotero.zotero_storage import (
                ZoteroOCRStorage,
                OCR_ATTACHMENT_MARKER,
            )

            mock_zot_instance = MagicMock()
            mock_zot_instance.children.return_value = [
                {"data": {"itemType": "attachment", "title": f"{OCR_ATTACHMENT_MARKER} doc"}}
            ]
            mock_zotero.return_value = mock_zot_instance

            storage = ZoteroOCRStorage()
            assert storage.has_ocr_conversion("ABC123")

    @patch("mistral_ocr_zotero.zotero_storage.zotero.Zotero")
    def test_store_ocr_result(self, mock_zotero: MagicMock) -> None:
        """Test storing OCR result creates local files and Zotero note."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(
                os.environ,
                {
                    "ZOTERO_LIBRARY_ID": "12345",
                    "ZOTERO_API_KEY": "test-api-key",
                },
            ):
                from mistral_ocr_zotero.zotero_storage import ZoteroOCRStorage

                mock_zot_instance = MagicMock()
                mock_zot_instance.create_items.return_value = {
                    "success": {"0": "NOTE123"}
                }
                mock_zotero.return_value = mock_zot_instance

                storage = ZoteroOCRStorage(storage_dir=Path(tmpdir))

                result = OCRResult(
                    markdown="# Test Document\n\nContent.",
                    images={"img.png": b"fake image"},
                    pages_processed=1,
                    source_file="test.pdf",
                )

                response = storage.store_ocr_result("ITEM123", result, "test.pdf")

                # Check local files were created
                item_dir = Path(tmpdir) / "ITEM123"
                assert item_dir.exists()
                assert (item_dir / "test_ocr.md").exists()
                assert (item_dir / "images" / "img.png").exists()
                assert (item_dir / "metadata.json").exists()

                # Check Zotero note was created
                assert response["key"] == "NOTE123"
