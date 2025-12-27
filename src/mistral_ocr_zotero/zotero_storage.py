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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pyzotero import zotero

from mistral_ocr_zotero.ocr_client import OCRResult

logger = logging.getLogger(__name__)

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
        if self.library_id is None:
            self.library_id = os.environ.get("ZOTERO_LIBRARY_ID", "0" if self.local else None)
        if self.api_key is None:
            self.api_key = os.environ.get("ZOTERO_API_KEY")

        if not self.library_id or not self.api_key:
            raise ValueError(
                "ZOTERO_LIBRARY_ID and ZOTERO_API_KEY must be provided or set in environment"
            )

        # Read client - uses local API if available for faster PDF access
        self._zotero = zotero.Zotero(
            self.library_id or "0",
            self.library_type,
            self.api_key,
            local=self.local
        )

        # Write client - always uses web API (local API is read-only)
        self._zotero_write = zotero.Zotero(
            self.library_id,
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

        Args:
            item_key: Zotero item key.

        Returns:
            True if OCR conversion exists.
        """
        return self.get_ocr_attachment(item_key) is not None

    def get_item_storage_dir(self, item_key: str) -> Path:
        """Get the local storage directory for an item's OCR results."""
        return self.storage_dir / item_key

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

        # Add metadata header to markdown
        header = f"""<!--
Mistral OCR Conversion
Source: {result.source_file or 'Unknown'}
Pages: {result.pages_processed}
Converted: {datetime.now().isoformat()}
-->

"""
        # Update image paths to use images/ subdirectory
        markdown_content = result.markdown
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
    ) -> dict[str, Any]:
        """Create a linked file attachment in Zotero via web API."""
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

        try:
            response = self.zot_write.create_items([attachment_data])
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
                # Local API returns different format
                attachment_key = response["successful"]["0"]["key"]
                logger.info(f"Created linked OCR attachment: {attachment_key} -> {md_path}")
                return {
                    "key": attachment_key,
                    "type": "linked_file",
                    "local_path": str(md_path),
                    "images_count": len(result.images),
                }
            else:
                logger.error(f"Failed to create linked attachment: {response}")
                return {"error": str(response), "local_path": str(md_path)}
        except Exception as e:
            logger.error(f"Error creating linked attachment: {e}")
            return {"error": str(e), "local_path": str(md_path)}

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
