"""End-to-end test for Mistral OCR Zotero integration."""

import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from pyzotero import zotero

# Load environment variables
load_dotenv()

def test_mistral_ocr_on_leishman():
    """Test Mistral OCR on the Leishman helicopter aerodynamics book."""

    # Import our modules
    from mistral_ocr_zotero import convert_to_markdown_enhanced

    # Connect to Zotero using local API (for locally stored PDFs)
    # Local API runs on port 23119 when Zotero is open
    print("Connecting to Zotero local API...")
    zot = zotero.Zotero("0", "user", api_key=None, local=True)

    # Get the Leishman helicopter book - test with momentum theory equations
    item_key = "T9Z23G55"
    print(f"Fetching item {item_key}...")
    item = zot.item(item_key)
    print(f"Title: {item['data']['title']}")

    # Get the PDF attachment
    children = zot.children(item_key)
    pdf_attachment = None
    for child in children:
        if child["data"].get("contentType") == "application/pdf":
            pdf_attachment = child
            break

    if not pdf_attachment:
        print("No PDF attachment found!")
        return

    attachment_key = pdf_attachment["key"]
    filename = pdf_attachment["data"].get("filename", f"{attachment_key}.pdf")
    print(f"Found PDF: {filename} (key: {attachment_key})")

    # Download PDF to temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / filename
        print(f"Downloading to {file_path}...")
        zot.dump(attachment_key, filename=filename, path=tmpdir)

        if not file_path.exists():
            print("Download failed!")
            return

        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        print(f"Downloaded: {file_size_mb:.1f} MB")

        # Process with Mistral OCR
        print("\nProcessing with Mistral OCR (this may take a few minutes for large PDFs)...")
        print("Note: Processing first 10 pages only for testing...")

        try:
            result = convert_to_markdown_enhanced(
                file_path,
                use_cache=False,  # Don't use cache for testing
                fallback_to_markitdown=True,
            )

            print(f"\n=== RESULT ===")
            print(f"Source: {result.source}")
            print(f"Cached: {result.cached}")
            if result.error:
                print(f"Error: {result.error}")
            print(f"Markdown length: {len(result.markdown)} chars")

            # Search for momentum theory content
            markdown = result.markdown
            if "momentum" in markdown.lower():
                print("\n=== MOMENTUM THEORY CONTENT FOUND ===")
                # Find and print context around "momentum"
                import re
                matches = list(re.finditer(r'.{0,200}momentum.{0,200}', markdown, re.IGNORECASE))
                for i, match in enumerate(matches[:3]):
                    print(f"\n--- Match {i+1} ---")
                    print(match.group().strip())
            else:
                print("\nNo 'momentum' content found in the extracted text.")
                print("\nFirst 2000 chars of output:")
                print(result.markdown[:2000])

        except Exception as e:
            print(f"Error during OCR: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    test_mistral_ocr_on_leishman()
