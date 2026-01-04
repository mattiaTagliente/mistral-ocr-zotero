"""
Zotero integration for OCR-processed documents.

This module provides the main integration layer that connects Mistral OCR
with Zotero libraries, handling the complete workflow of PDF conversion,
storage, and retrieval.
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pyzotero import zotero

from mistral_ocr_zotero.converter import convert_to_markdown_enhanced, ConversionResult
from mistral_ocr_zotero.ocr_client import MistralOCRClient, OCRResult
from mistral_ocr_zotero.zotero_storage import ZoteroOCRStorage, OCR_ATTACHMENT_MARKER

logger = logging.getLogger(__name__)


class FileNotAccessibleError(Exception):
    """
    Raised when a file exists but is not accessible.
    
    This commonly occurs with cloud sync services (OneDrive, Dropbox, etc.)
    where files appear to exist locally but are actually cloud-only placeholders
    that haven't been synced.
    """
    pass


@dataclass
class ZoteroOCRIntegration:
    """
    Main integration class for Mistral OCR with Zotero.

    Provides methods to:
    - Check if items have OCR conversions
    - Process PDFs through Mistral OCR
    - Store and retrieve OCR results
    - Get enhanced full text for Zotero items
    """

    library_id: str | None = None
    library_type: str = "user"
    api_key: str | None = field(default=None, repr=False)
    mistral_api_key: str | None = field(default=None, repr=False)
    local: bool = field(default=False)

    _zotero: Any | None = field(default=None, init=False, repr=False)
    _ocr_client: MistralOCRClient | None = field(default=None, init=False, repr=False)
    _storage: ZoteroOCRStorage | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        # Check for local mode from environment
        if os.environ.get("ZOTERO_LOCAL", "").lower() in ["true", "yes", "1"]:
            self.local = True

        # Load from environment if not provided
        if self.library_id is None:
            self.library_id = os.environ.get("ZOTERO_LIBRARY_ID", "0" if self.local else None)
        if self.api_key is None:
            self.api_key = os.environ.get("ZOTERO_API_KEY")
        if self.mistral_api_key is None:
            self.mistral_api_key = os.environ.get("MISTRAL_API_KEY")

        if not self.library_id or not self.api_key:
            raise ValueError(
                "ZOTERO_LIBRARY_ID and ZOTERO_API_KEY must be provided or set in environment"
            )

        # Use local API for reads (faster PDF access)
        self._zotero = zotero.Zotero(self.library_id, self.library_type, self.api_key, local=self.local)

        # Initialize OCR client (may fail if no Mistral key, that's ok for fallback)
        try:
            self._ocr_client = MistralOCRClient(api_key=self.mistral_api_key)
        except ValueError:
            logger.warning("Mistral API key not configured, OCR will use fallback only")
            self._ocr_client = None

        # Initialize storage
        self._storage = ZoteroOCRStorage(
            library_id=self.library_id,
            library_type=self.library_type,
            api_key=self.api_key,
            local=self.local,
        )

    @property
    def zot(self) -> Any:
        """Get the Zotero client instance."""
        if self._zotero is None:
            raise RuntimeError("Zotero client not initialized")
        return self._zotero

    @property
    def ocr(self) -> MistralOCRClient | None:
        """Get the OCR client instance (may be None if not configured)."""
        return self._ocr_client

    @property
    def storage(self) -> ZoteroOCRStorage:
        """Get the storage instance."""
        if self._storage is None:
            raise RuntimeError("Storage not initialized")
        return self._storage

    def _process_pdf_file(
        self,
        pdf_path: Path,
        item_key: str,
        store_in_zotero: bool = True,
        original_filename: str | None = None,
    ) -> OCRResult | None:
        """
        Process a PDF file through Mistral OCR.

        Args:
            pdf_path: Path to the PDF file.
            item_key: Zotero item key for storage.
            store_in_zotero: Whether to store the result in Zotero.
            original_filename: Original filename for storage reference.

        Returns:
            OCRResult if successful, None otherwise.
        """
        if self.ocr is None:
            logger.error("OCR client not initialized")
            return None

        try:
            result = self.ocr.process_pdf_from_path(pdf_path)
            logger.info(
                f"OCR complete: {result.pages_processed} pages, "
                f"{len(result.images)} images extracted"
            )
        except Exception as e:
            logger.error(f"OCR processing failed: {e}")
            return None

        # Store result
        if store_in_zotero:
            filename = original_filename or pdf_path.name
            self.storage.store_ocr_result(item_key, result, filename)

        return result

    def _is_file_accessible(self, file_path: Path, timeout_seconds: float = 5.0) -> bool:
        """
        Check if a file is actually accessible (not a cloud-only placeholder).

        On Windows with OneDrive/cloud sync, files can appear to exist (Path.exists()
        returns True) but are actually cloud-only placeholders. Attempting to read
        these files will either hang (waiting for sync) or fail.

        This method attempts to read a small portion of the file with a timeout
        to verify it's truly accessible.

        Args:
            file_path: Path to the file to check.
            timeout_seconds: Maximum time to wait for file access.

        Returns:
            True if the file is accessible, False otherwise.
        """
        import threading
        import time

        result = {"accessible": False, "error": None}

        def try_read():
            try:
                with open(file_path, "rb") as f:
                    # Try to read just the first few bytes
                    _ = f.read(1024)
                result["accessible"] = True
            except Exception as e:
                result["error"] = str(e)

        # Run file read in a separate thread with timeout
        read_thread = threading.Thread(target=try_read)
        read_thread.daemon = True
        read_thread.start()
        read_thread.join(timeout=timeout_seconds)

        if read_thread.is_alive():
            # Thread is still running - file access is hanging (likely cloud-only)
            logger.warning(
                f"File access timed out after {timeout_seconds}s - "
                f"file may be cloud-only: {file_path}"
            )
            return False

        if not result["accessible"]:
            logger.warning(f"File not accessible: {file_path} - {result['error']}")
            return False

        return True

    def has_ocr_conversion(self, item_key: str) -> bool:
        """
        Check if an item already has an OCR-converted markdown.

        Args:
            item_key: Zotero item key.

        Returns:
            True if OCR conversion already exists.
        """
        return self.storage.has_ocr_conversion(item_key)

    def get_pdf_attachment(self, item_key: str) -> dict[str, Any] | None:
        """
        Get the PDF attachment for a Zotero item.

        Args:
            item_key: Zotero item key.

        Returns:
            Attachment data dict or None if no PDF found.
        """
        try:
            children = self.zot.children(item_key)
            for child in children:
                data = child.get("data", {})
                if data.get("itemType") == "attachment":
                    content_type = data.get("contentType", "")
                    if content_type == "application/pdf":
                        return child
            return None
        except Exception as e:
            logger.warning(f"Error getting PDF attachment: {e}")
            return None

    def process_item(
        self,
        item_key: str,
        force: bool = False,
        store_in_zotero: bool = True,
    ) -> OCRResult | None:
        """
        Process a Zotero item's PDF through Mistral OCR.

        Args:
            item_key: Zotero item key.
            force: Force reprocessing even if conversion exists.
            store_in_zotero: Store the result as a Zotero attachment.

        Returns:
            OCRResult if processing occurred, None if skipped.
        """
        # Check for existing conversion
        if not force and self.has_ocr_conversion(item_key):
            logger.info(f"Item {item_key} already has OCR conversion, skipping")
            return None

        # Get PDF attachment
        pdf_attachment = self.get_pdf_attachment(item_key)
        if pdf_attachment is None:
            logger.warning(f"No PDF attachment found for item {item_key}")
            return None

        attachment_key = pdf_attachment.get("key")
        
        # Try to get a meaningful filename from multiple sources
        data = pdf_attachment.get("data", {})
        filename = data.get("filename") or data.get("title")
        
        # Debug logging for filename detection
        logger.debug(f"PDF attachment data keys: {list(data.keys())}")
        logger.debug(f"PDF attachment filename from data: {data.get('filename')}")
        logger.debug(f"PDF attachment title from data: {data.get('title')}")
        
        # If still no filename, try to get parent item info for a meaningful name
        if not filename or filename == "document.pdf":
            try:
                parent_item = self.zot.item(item_key)
                parent_data = parent_item.get("data", {})
                # Use citation key if available, otherwise title
                citation_key = parent_data.get("citationKey")
                title = parent_data.get("title", "")
                
                if citation_key:
                    filename = f"{citation_key}.pdf"
                    logger.info(f"Using citation key for filename: {filename}")
                elif title:
                    # Clean title for use as filename
                    import re
                    clean_title = re.sub(r'[<>:"/\\|?*]', '', title)[:80]
                    filename = f"{clean_title}.pdf"
                    logger.info(f"Using cleaned title for filename: {filename}")
                else:
                    filename = "document.pdf"
            except Exception as e:
                logger.warning(f"Could not get parent item for filename: {e}")
                filename = "document.pdf"

        logger.info(f"Processing PDF {filename} for item {item_key}")

        # Check if this is a linked file (path stored locally) vs imported file
        link_mode = data.get("linkMode", "")
        local_path = data.get("path", "")
        
        # For linked files, read directly from disk
        if link_mode == "linked_file" and local_path:
            # Clean up the path (Zotero stores it with possible prefix)
            if local_path.startswith("attachments:"):
                # Relative to Zotero attachments base dir - need to resolve
                logger.warning(f"Relative attachment path not supported: {local_path}")
                local_path = ""
            
            if local_path:
                pdf_source_path = Path(local_path)
                if pdf_source_path.exists():
                    # Check if file is actually accessible (not a cloud-only placeholder)
                    if not self._is_file_accessible(pdf_source_path):
                        error_msg = (
                            f"File is not available locally: {pdf_source_path}. "
                            f"This file may be stored in the cloud (OneDrive/Dropbox/etc.) "
                            f"but not synced to this computer. Please ensure the file is "
                            f"downloaded locally before processing."
                        )
                        logger.error(error_msg)
                        raise FileNotAccessibleError(error_msg)
                    logger.info(f"Using linked file directly: {pdf_source_path}")
                    return self._process_pdf_file(pdf_source_path, item_key, store_in_zotero, filename)
                else:
                    logger.error(f"Linked file not found: {pdf_source_path}")
                    return None

        # For imported files or if linked file path didn't work, use dump()
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / filename
            try:
                self.zot.dump(attachment_key, path=tmpdir, filename=filename)
            except Exception as e:
                logger.error(f"Failed to download PDF: {e}")
                return None

            if not pdf_path.exists():
                logger.error(f"PDF download failed, file not found: {pdf_path}")
                return None

            return self._process_pdf_file(pdf_path, item_key, store_in_zotero, filename)

    def get_fulltext_with_ocr(
        self,
        item_key: str,
        fallback_to_extraction: bool = True,
    ) -> str:
        """
        Get full text for an item, using OCR if available.

        This method is designed to enhance/replace the Zotero-MCP get_fulltext tool.
        It checks for existing OCR conversions first, then falls back to processing
        the PDF if needed.

        Args:
            item_key: Zotero item key.
            fallback_to_extraction: Fall back to standard extraction if OCR fails.

        Returns:
            Markdown text content.
        """
        # Check for existing OCR conversion
        existing_content = self.storage.get_ocr_content(item_key)
        if existing_content:
            logger.info(f"Using existing OCR conversion for {item_key}")
            return existing_content

        # Try to process the PDF
        try:
            result = self.process_item(item_key, store_in_zotero=True)
            if result:
                return result.markdown
        except Exception as e:
            logger.warning(f"OCR processing failed: {e}")
            if not fallback_to_extraction:
                raise

        # Fallback to standard Zotero full-text extraction
        logger.info(f"Falling back to standard extraction for {item_key}")
        return self._fallback_extraction(item_key)

    def _fallback_extraction(self, item_key: str) -> str:
        """
        Fallback to standard PDF text extraction.

        Args:
            item_key: Zotero item key.

        Returns:
            Extracted text content.
        """
        # Get PDF attachment
        pdf_attachment = self.get_pdf_attachment(item_key)
        if pdf_attachment is None:
            return f"No PDF attachment found for item {item_key}"

        attachment_key = pdf_attachment.get("key")

        # Try Zotero's built-in full text index
        try:
            fulltext_data = self.zot.fulltext_item(attachment_key)
            if fulltext_data and "content" in fulltext_data:
                return fulltext_data["content"]
        except Exception as e:
            logger.debug(f"Zotero fulltext not available: {e}")

        # Download and convert with markitdown
        filename = pdf_attachment.get("data", {}).get("filename", "document.pdf")

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / filename
            try:
                self.zot.dump(attachment_key, path=tmpdir, filename=filename)
            except Exception as e:
                return f"Failed to download PDF: {e}"

            if not pdf_path.exists():
                return "PDF download failed"

            try:
                from markitdown import MarkItDown

                md = MarkItDown()
                result = md.convert(str(pdf_path))
                return result.text_content
            except Exception as e:
                return f"Error converting PDF: {e}"

    def batch_process(
        self,
        item_keys: list[str] | None = None,
        collection_key: str | None = None,
        limit: int = 50,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Batch process multiple items through OCR.

        Args:
            item_keys: List of specific item keys to process.
            collection_key: Process all items in a collection.
            limit: Maximum number of items to process.
            force: Force reprocessing even if conversions exist.

        Returns:
            Summary of processing results.
        """
        results = {
            "processed": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
        }

        # Get items to process
        if item_keys:
            items_to_process = item_keys[:limit]
        elif collection_key:
            collection_items = self.zot.collection_items(collection_key, limit=limit)
            items_to_process = [
                item["key"]
                for item in collection_items
                if item.get("data", {}).get("itemType") != "attachment"
            ]
        else:
            # Process recent items
            recent_items = self.zot.items(limit=limit, sort="dateAdded", direction="desc")
            items_to_process = [
                item["key"]
                for item in recent_items
                if item.get("data", {}).get("itemType") != "attachment"
            ]

        logger.info(f"Batch processing {len(items_to_process)} items")

        for item_key in items_to_process:
            try:
                result = self.process_item(item_key, force=force)
                if result:
                    results["processed"] += 1
                else:
                    results["skipped"] += 1
            except Exception as e:
                results["failed"] += 1
                results["errors"].append({"item_key": item_key, "error": str(e)})
                logger.error(f"Failed to process {item_key}: {e}")

        logger.info(
            f"Batch complete: {results['processed']} processed, "
            f"{results['skipped']} skipped, {results['failed']} failed"
        )

        return results
