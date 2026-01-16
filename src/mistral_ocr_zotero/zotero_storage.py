"""
Zotero storage integration for OCR results.

This module handles storing and retrieving OCR-converted markdown documents
as Zotero attachments, enabling persistent storage within the Zotero library.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pyzotero import zotero

from mistral_ocr_zotero.ocr_client import OCRResult

logger = logging.getLogger(__name__)
# Add file handler for debugging
_fh = logging.FileHandler(str(Path.home() / "mistral_ocr_debug.log"))
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(_fh)
logger.setLevel(logging.DEBUG)

# Marker used to identify OCR-converted attachments
OCR_ATTACHMENT_MARKER = "[Mistral-OCR]"


@dataclass
class ZoteroOCRStorage:
    """
    Manages OCR result storage within Zotero library.

    Stores converted markdown documents as linked file attachments,
    enabling retrieval through the standard Zotero attachment system.
    """

    library_id: str | None = None
    library_type: str = "user"
    api_key: str | None = field(default=None, repr=False)
    local: bool = field(default=False)
    storage_dir: Path = field(
        default_factory=lambda: Path.home() / ".local" / "share" / "mistral-ocr-zotero"
    )

    _zotero: Any | None = field(default=None, init=False, repr=False)
    _zotero_write: Any | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        # Check for local mode from environment
        if os.environ.get("ZOTERO_LOCAL", "").lower() in ["true", "yes", "1"]:
            self.local = True

        # Load from environment if not provided
        env_library_id = os.environ.get("ZOTERO_LIBRARY_ID")
        if self.library_id is None:
            self.library_id = env_library_id
        if self.api_key is None:
            self.api_key = os.environ.get("ZOTERO_API_KEY")

        # Determine library IDs for read and write clients
        # Read client: Local API accepts "0" as shorthand for current user
        # Write client: Web API REQUIRES the actual library ID (never "0")
        read_library_id = self.library_id or ("0" if self.local else None)
        write_library_id = self.library_id  # Must be real ID, not "0"

        logger.debug(f"ZoteroOCRStorage init: local={self.local}, library_id={self.library_id}, "
                     f"read_id={read_library_id}, write_id={write_library_id}")

        if not write_library_id or not self.api_key:
            raise ValueError(
                "ZOTERO_LIBRARY_ID and ZOTERO_API_KEY must be provided or set in environment. "
                f"Got library_id={self.library_id}, api_key={'set' if self.api_key else 'not set'}"
            )

        # Read client - uses local API if available for faster PDF access
        self._zotero = zotero.Zotero(
            read_library_id,
            self.library_type,
            self.api_key,
            local=self.local
        )

        # Write client - always uses web API with real library ID (local API is read-only)
        self._zotero_write = zotero.Zotero(
            write_library_id,
            self.library_type,
            self.api_key,
            local=False  # Always use web API for writes
        )
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    @property
    def zot(self) -> Any:
        """Get the Zotero client instance (for reads)."""
        if self._zotero is None:
            raise RuntimeError("Zotero client not initialized")
        return self._zotero

    @property
    def zot_write(self) -> Any:
        """Get the Zotero write client (web API, for creating items)."""
        if self._zotero_write is None:
            raise RuntimeError("Zotero write client not initialized")
        return self._zotero_write

    def get_ocr_attachment(self, item_key: str) -> dict[str, Any] | None:
        """
        Find existing OCR attachment for a Zotero item.

        Args:
            item_key: Zotero item key.

        Returns:
            Attachment data dict or None if not found.
        """
        try:
            children = self.zot.children(item_key)
            for child in children:
                data = child.get("data", {})
                if data.get("itemType") == "attachment":
                    title = data.get("title", "")
                    # Check for our OCR marker
                    if OCR_ATTACHMENT_MARKER in title:
                        return child
            return None
        except Exception as e:
            logger.warning(f"Error checking for OCR attachment: {e}")
            return None

    def has_ocr_attachment(self, item_key: str) -> bool:
        """
        Check if an item has an OCR attachment in Zotero.

        Args:
            item_key: Zotero item key.

        Returns:
            True if OCR attachment exists.
        """
        return self.get_ocr_attachment(item_key) is not None

    def has_ocr_conversion(self, item_key: str) -> bool:
        """
        Check if an item already has an OCR conversion.

        Checks both local storage and Zotero attachment.

        Args:
            item_key: Zotero item key.

        Returns:
            True if OCR conversion exists (locally or in Zotero).
        """
        # Check local storage first (faster, no API call)
        item_dir = self.get_item_storage_dir(item_key)
        if item_dir.exists():
            md_files = list(item_dir.glob("*_ocr.md"))
            if md_files:
                return True
        # Fall back to checking Zotero attachment
        return self.get_ocr_attachment(item_key) is not None

    def get_item_storage_dir(self, item_key: str) -> Path:
        """Get the local storage directory for an item's OCR results."""
        return self.storage_dir / item_key

    def create_attachment_only(
        self,
        item_key: str,
        pdf_filename: str | None = None,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """
        Create Zotero attachment for existing local OCR file without rewriting it.

        Use this when local storage exists but Zotero attachment is missing,
        to avoid header stacking and unnecessary file I/O.

        Args:
            item_key: Parent Zotero item key.
            pdf_filename: Original PDF filename for attachment title.
            max_retries: Maximum number of retry attempts for API failures.

        Returns:
            Created attachment data or error dict.
        """
        # Find existing local file
        item_dir = self.get_item_storage_dir(item_key)
        if not item_dir.exists():
            logger.error(f"No local storage found for {item_key} at {item_dir}")
            return {"error": f"No local storage found for {item_key}"}

        md_files = list(item_dir.glob("*_ocr.md"))
        if not md_files:
            logger.error(f"No OCR markdown file found in {item_dir}")
            return {"error": f"No OCR markdown file found in {item_dir}"}

        md_path = md_files[0]  # Use first match
        logger.info(f"Found local OCR file: {md_path}")

        # Double-check for existing attachment to handle race conditions
        # (another request might have created it while we were processing)
        if self.has_ocr_attachment(item_key):
            logger.info(f"Attachment already exists for {item_key} (race condition avoided)")
            return {
                "key": "existing",
                "type": "linked_file",
                "local_path": str(md_path),
                "note": "Attachment already existed (race condition)",
            }

        # Generate attachment title - use filename stem or item key as fallback
        if pdf_filename and pdf_filename.strip():
            base_name = Path(pdf_filename).stem
        else:
            # Fallback: try to extract from local file name
            base_name = md_path.stem.replace("_ocr", "") or item_key
            logger.warning(f"No pdf_filename provided, using fallback: {base_name}")
        attachment_title = f"{OCR_ATTACHMENT_MARKER} {base_name}"

        # Create the linked file attachment via web API
        attachment_data = {
            "itemType": "attachment",
            "parentItem": item_key,
            "linkMode": "linked_file",
            "title": attachment_title,
            "path": str(md_path.absolute()),
            "contentType": "text/markdown",
            "tags": [{"tag": "mistral-ocr"}, {"tag": "ocr-converted"}],
        }

        logger.debug(f"Attachment data: {attachment_data}")

        last_error = None
        for attempt in range(max_retries):
            try:
                # Check again for race condition before each attempt
                if attempt > 0 and self.has_ocr_attachment(item_key):
                    logger.info(f"Attachment created by concurrent request for {item_key}")
                    return {
                        "key": "existing",
                        "type": "linked_file",
                        "local_path": str(md_path),
                        "note": "Attachment created by concurrent request",
                    }

                response = self.zot_write.create_items([attachment_data])
                logger.info(f"Zotero API response (attempt {attempt + 1}): {response}")

                # Handle various response formats from Zotero API
                if response.get("success"):
                    attachment_key = list(response["success"].values())[0]
                    logger.info(f"Created linked OCR attachment: {attachment_key} -> {md_path}")
                    return {
                        "key": attachment_key,
                        "type": "linked_file",
                        "local_path": str(md_path),
                    }
                elif response.get("successful"):
                    # Alternative response format
                    first_key = list(response["successful"].keys())[0]
                    attachment_key = response["successful"][first_key].get("key")
                    if attachment_key:
                        logger.info(f"Created linked OCR attachment: {attachment_key} -> {md_path}")
                        return {
                            "key": attachment_key,
                            "type": "linked_file",
                            "local_path": str(md_path),
                        }

                # Check for failure details
                failed = response.get("failed", {}) or response.get("failure", {})
                if failed:
                    error_details = str(failed)
                    logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {error_details}")
                    last_error = error_details
                else:
                    # Unknown response format
                    logger.warning(f"Attempt {attempt + 1}/{max_retries} - unexpected response: {response}")
                    last_error = str(response)

            except Exception as e:
                logger.warning(f"Attempt {attempt + 1}/{max_retries} exception: {e}")
                last_error = str(e)

            # Wait before retry with exponential backoff
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 1s, 2s, 4s
                logger.info(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)

        # All retries exhausted
        logger.error(f"Failed to create linked attachment after {max_retries} attempts: {last_error}")
        return {"error": f"Failed after {max_retries} attempts: {last_error}", "local_path": str(md_path)}

    def store_ocr_result(
        self,
        item_key: str,
        result: OCRResult,
        pdf_filename: str | None = None,
    ) -> dict[str, Any]:
        """
        Store OCR result and create Zotero linked file attachment.

        Args:
            item_key: Parent Zotero item key.
            result: OCR result to store.
            pdf_filename: Original PDF filename for reference.

        Returns:
            Created attachment data.
        """
        # Create storage directory for this item
        item_dir = self.get_item_storage_dir(item_key)
        item_dir.mkdir(parents=True, exist_ok=True)

        # Generate markdown filename
        base_name = Path(pdf_filename).stem if pdf_filename else item_key
        md_filename = f"{base_name}_ocr.md"
        md_path = item_dir / md_filename

        # Update image paths to use images/ subdirectory
        markdown_content = result.markdown

        # Robust protection against header stacking: strip ALL existing OCR headers
        # Use regex to find and remove all Mistral OCR Conversion comment blocks
        header_pattern = re.compile(
            r'^<!--\s*\n?Mistral OCR Conversion\s*\n'
            r'(?:Source:.*?\n)?'
            r'(?:Pages:.*?\n)?'
            r'(?:Converted:.*?\n)?'
            r'-->\s*\n*',
            re.MULTILINE
        )
        original_len = len(markdown_content)
        markdown_content = header_pattern.sub('', markdown_content)
        if len(markdown_content) < original_len:
            headers_removed = (original_len - len(markdown_content)) // 100  # Rough estimate
            logger.info(f"Stripped existing OCR headers to prevent stacking (removed ~{headers_removed} headers)")

        # Add fresh metadata header to markdown
        header = f"""<!--
Mistral OCR Conversion
Source: {result.source_file or 'Unknown'}
Pages: {result.pages_processed}
Converted: {datetime.now().isoformat()}
-->

"""
        if result.images:
            # Update image references: ![...](img-N.jpeg) -> ![...](images/img-N.jpeg)
            markdown_content = re.sub(r'\]\((img-\d+\.[a-z]+)\)', r'](images/\1)', markdown_content)

        # Inline tables: replace [tbl-N.md](tbl-N.md) with actual table content
        tables = getattr(result, 'tables', {})
        if tables:
            for tbl_id, tbl_content in tables.items():
                # Replace link reference with inline table content
                # Use str.replace() instead of re.sub() to avoid escape sequence issues
                link_pattern = f'[{tbl_id}]({tbl_id})'
                replacement = f'\n\n{tbl_content}\n\n'
                markdown_content = markdown_content.replace(link_pattern, replacement)
            logger.info(f"Inlined {len(tables)} tables into markdown")

        full_markdown = header + markdown_content

        # Save markdown file
        md_path.write_text(full_markdown, encoding="utf-8")
        logger.info(f"Saved OCR markdown to {md_path}")

        # Save images if present
        if result.images:
            images_dir = item_dir / "images"
            images_dir.mkdir(exist_ok=True)
            for filename, data in result.images.items():
                (images_dir / filename).write_bytes(data)
            logger.info(f"Saved {len(result.images)} images to {images_dir}")

        # Save metadata
        metadata = {
            "source_file": result.source_file,
            "pages_processed": result.pages_processed,
            "images_count": len(result.images),
            "converted_at": datetime.now().isoformat(),
            "markdown_path": str(md_path),
            "item_key": item_key,
        }
        metadata_path = item_dir / "metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        # Create Zotero linked file attachment
        attachment_title = f"{OCR_ATTACHMENT_MARKER} {base_name}"

        # For local Zotero, create a linked file attachment pointing to the markdown
        if self.local:
            logger.info(f"store_ocr_result: calling _create_linked_attachment for {item_key}, local={self.local}")
            return self._create_linked_attachment(item_key, md_path, attachment_title, result)
        else:
            # For web API, create a note with the content
            return self._create_note_attachment(item_key, full_markdown, attachment_title, md_path)

    def _create_linked_attachment(
        self,
        item_key: str,
        md_path: Path,
        title: str,
        result: OCRResult,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Create a linked file attachment in Zotero via web API with retry logic."""
        logger.info(f"_create_linked_attachment called: item={item_key}, title={title}, path={md_path}")
        # Use web API to create linked file attachment (local API is read-only)
        attachment_data = {
            "itemType": "attachment",
            "parentItem": item_key,
            "linkMode": "linked_file",
            "title": title,
            "path": str(md_path.absolute()),
            "contentType": "text/markdown",
            "tags": [{"tag": "mistral-ocr"}, {"tag": "ocr-converted"}],
        }

        logger.debug(f"Creating linked attachment: {attachment_data}")

        last_error = None
        for attempt in range(max_retries):
            try:
                # Check for race condition before each retry
                if attempt > 0 and self.has_ocr_attachment(item_key):
                    logger.info(f"Attachment created by concurrent request for {item_key}")
                    return {
                        "key": "existing",
                        "type": "linked_file",
                        "local_path": str(md_path),
                        "images_count": len(result.images),
                        "note": "Attachment created by concurrent request",
                    }

                response = self.zot_write.create_items([attachment_data])
                logger.info(f"Zotero API response (attempt {attempt + 1}): {response}")

                if response.get("success"):
                    attachment_key = list(response["success"].values())[0]
                    logger.info(f"Created linked OCR attachment: {attachment_key} -> {md_path}")
                    return {
                        "key": attachment_key,
                        "type": "linked_file",
                        "local_path": str(md_path),
                        "images_count": len(result.images),
                    }
                elif response.get("successful"):
                    # Alternative response format
                    first_key = list(response["successful"].keys())[0]
                    attachment_key = response["successful"][first_key].get("key")
                    if attachment_key:
                        logger.info(f"Created linked OCR attachment: {attachment_key} -> {md_path}")
                        return {
                            "key": attachment_key,
                            "type": "linked_file",
                            "local_path": str(md_path),
                            "images_count": len(result.images),
                        }

                # Check for failure details
                failed = response.get("failed", {}) or response.get("failure", {})
                if failed:
                    error_details = str(failed)
                    logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {error_details}")
                    last_error = error_details
                else:
                    logger.warning(f"Attempt {attempt + 1}/{max_retries} - unexpected response: {response}")
                    last_error = str(response)

            except Exception as e:
                logger.warning(f"Attempt {attempt + 1}/{max_retries} exception: {e}")
                last_error = str(e)

            # Wait before retry with exponential backoff
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.info(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)

        # All retries exhausted
        logger.error(f"Failed to create linked attachment after {max_retries} attempts: {last_error}")
        return {"error": f"Failed after {max_retries} attempts: {last_error}", "local_path": str(md_path)}

    def _create_note_attachment(
        self,
        item_key: str,
        full_markdown: str,
        title: str,
        md_path: Path,
    ) -> dict[str, Any]:
        """Create a note attachment for web API."""
        # Truncate if too long for Zotero note (limit is ~1MB)
        max_note_size = 500000  # 500KB to be safe
        if len(full_markdown) > max_note_size:
            truncated_markdown = full_markdown[:max_note_size]
            truncated_markdown += f"\n\n---\n*[Content truncated. Full version: {md_path}]*"
        else:
            truncated_markdown = full_markdown

        # Convert markdown to HTML for Zotero note
        note_html = self._markdown_to_html(truncated_markdown)

        note_data = {
            "itemType": "note",
            "parentItem": item_key,
            "note": f"<h1>{title}</h1>\n{note_html}",
            "tags": [{"tag": "mistral-ocr"}, {"tag": "ocr-converted"}],
        }

        try:
            response = self.zot.create_items([note_data])
            if response.get("success"):
                note_key = list(response["success"].values())[0]
                logger.info(f"Created OCR note attachment: {note_key}")
                return {"key": note_key, "type": "note", "local_path": str(md_path)}
            else:
                logger.error(f"Failed to create note: {response}")
                return {"error": str(response), "local_path": str(md_path)}
        except Exception as e:
            logger.error(f"Error creating Zotero note: {e}")
            return {"error": str(e), "local_path": str(md_path)}

    def _markdown_to_html(self, markdown: str) -> str:
        """
        Convert markdown to simple HTML for Zotero notes.

        Args:
            markdown: Markdown content.

        Returns:
            HTML string suitable for Zotero notes.
        """
        # Simple conversion - Zotero notes support basic HTML
        lines = markdown.split("\n")
        html_lines = []

        in_code_block = False
        for line in lines:
            if line.startswith("```"):
                if in_code_block:
                    html_lines.append("</pre>")
                    in_code_block = False
                else:
                    html_lines.append("<pre>")
                    in_code_block = True
                continue

            if in_code_block:
                html_lines.append(line)
                continue

            # Headers
            if line.startswith("# "):
                html_lines.append(f"<h1>{line[2:]}</h1>")
            elif line.startswith("## "):
                html_lines.append(f"<h2>{line[3:]}</h2>")
            elif line.startswith("### "):
                html_lines.append(f"<h3>{line[4:]}</h3>")
            elif line.startswith("#### "):
                html_lines.append(f"<h4>{line[5:]}</h4>")
            # Bold
            elif "**" in line:
                import re
                line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
                html_lines.append(f"<p>{line}</p>")
            # Empty line = paragraph break
            elif not line.strip():
                html_lines.append("<p></p>")
            else:
                html_lines.append(f"<p>{line}</p>")

        return "\n".join(html_lines)

    def get_ocr_content(self, item_key: str) -> str | None:
        """
        Retrieve stored OCR markdown content for an item.

        Args:
            item_key: Zotero item key.

        Returns:
            Markdown content or None if not found.
        """
        # First check local storage
        item_dir = self.get_item_storage_dir(item_key)
        if item_dir.exists():
            for md_file in item_dir.glob("*_ocr.md"):
                return md_file.read_text(encoding="utf-8")

        # Fall back to Zotero note attachment
        attachment = self.get_ocr_attachment(item_key)
        if attachment:
            data = attachment.get("data", {})
            if data.get("itemType") == "note":
                # Extract text from HTML note
                note_html = data.get("note", "")
                return self._html_to_text(note_html)

        return None

    def _html_to_text(self, html: str) -> str:
        """
        Extract text from HTML note content.

        Args:
            html: HTML content.

        Returns:
            Plain text / markdown approximation.
        """
        import re

        # Remove HTML tags but preserve structure
        text = html
        text = re.sub(r'<h1>(.*?)</h1>', r'# \1\n', text)
        text = re.sub(r'<h2>(.*?)</h2>', r'## \1\n', text)
        text = re.sub(r'<h3>(.*?)</h3>', r'### \1\n', text)
        text = re.sub(r'<h4>(.*?)</h4>', r'#### \1\n', text)
        text = re.sub(r'<strong>(.*?)</strong>', r'**\1**', text)
        text = re.sub(r'<p>(.*?)</p>', r'\1\n', text)
        text = re.sub(r'<pre>(.*?)</pre>', r'```\n\1\n```\n', text, flags=re.DOTALL)
        text = re.sub(r'<br\s*/?>', '\n', text)
        text = re.sub(r'<[^>]+>', '', text)  # Remove remaining tags

        return text.strip()

    # ========== Chunk Progress Storage ==========

    def get_chunks_dir(self, item_key: str) -> Path:
        """Get the directory for storing chunk progress."""
        return self.storage_dir / item_key / "chunks"

    def save_chunk_result(
        self,
        item_key: str,
        chunk_index: int,
        result: OCRResult,
        chunk_info: dict[str, Any],
    ) -> None:
        """
        Save a single chunk's OCR result for later resumption.

        Args:
            item_key: Zotero item key.
            chunk_index: Index of the chunk (0-based).
            result: OCR result for this chunk.
            chunk_info: Chunk metadata (start_page, end_page, title).
        """
        chunks_dir = self.get_chunks_dir(item_key)
        chunks_dir.mkdir(parents=True, exist_ok=True)

        chunk_data = {
            "chunk_index": chunk_index,
            "chunk_info": chunk_info,
            "markdown": result.markdown,
            "pages_processed": result.pages_processed,
            "source_file": result.source_file,
            "tables": result.tables,
            "saved_at": datetime.now().isoformat(),
        }

        # Save images separately (binary data)
        if result.images:
            images_dir = chunks_dir / f"chunk_{chunk_index:03d}_images"
            images_dir.mkdir(exist_ok=True)
            chunk_data["images_dir"] = str(images_dir)
            for filename, data in result.images.items():
                (images_dir / filename).write_bytes(data)

        # Save chunk metadata
        chunk_file = chunks_dir / f"chunk_{chunk_index:03d}.json"
        with open(chunk_file, "w", encoding="utf-8") as f:
            json.dump(chunk_data, f, indent=2)

        logger.info(f"Saved chunk {chunk_index} progress for item {item_key}")

    def load_chunk_result(
        self,
        item_key: str,
        chunk_index: int,
    ) -> tuple[OCRResult, dict[str, Any]] | None:
        """
        Load a saved chunk's OCR result.

        Args:
            item_key: Zotero item key.
            chunk_index: Index of the chunk (0-based).

        Returns:
            Tuple of (OCRResult, chunk_info) if saved, None otherwise.
        """
        chunk_file = self.get_chunks_dir(item_key) / f"chunk_{chunk_index:03d}.json"
        if not chunk_file.exists():
            return None

        with open(chunk_file, "r", encoding="utf-8") as f:
            chunk_data = json.load(f)

        # Load images if present
        images: dict[str, bytes] = {}
        if "images_dir" in chunk_data:
            images_dir = Path(chunk_data["images_dir"])
            if images_dir.exists():
                for img_file in images_dir.iterdir():
                    images[img_file.name] = img_file.read_bytes()

        result = OCRResult(
            markdown=chunk_data["markdown"],
            images=images,
            pages_processed=chunk_data["pages_processed"],
            source_file=chunk_data.get("source_file"),
            tables=chunk_data.get("tables", {}),
        )

        return result, chunk_data["chunk_info"]

    def get_saved_chunk_indices(self, item_key: str) -> list[int]:
        """
        Get list of chunk indices that have been saved.

        Args:
            item_key: Zotero item key.

        Returns:
            List of saved chunk indices (sorted).
        """
        chunks_dir = self.get_chunks_dir(item_key)
        if not chunks_dir.exists():
            return []

        indices = []
        for chunk_file in chunks_dir.glob("chunk_*.json"):
            # Extract index from filename like "chunk_003.json"
            try:
                index = int(chunk_file.stem.split("_")[1])
                indices.append(index)
            except (IndexError, ValueError):
                continue

        return sorted(indices)

    def clear_chunk_results(self, item_key: str) -> None:
        """
        Clear all saved chunk progress after successful completion.

        Args:
            item_key: Zotero item key.
        """
        chunks_dir = self.get_chunks_dir(item_key)
        if chunks_dir.exists():
            import shutil
            shutil.rmtree(chunks_dir)
            logger.info(f"Cleared chunk progress for item {item_key}")
