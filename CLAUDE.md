# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MistralOCR_Zotero integrates the Mistral OCR API with Zotero-MCP to convert PDF documents in a Zotero library into markdown format with properly formatted figures, equations, and tables. This improves LLM access to full-text content compared to standard PDF text extraction.

## Architecture

### Core Modules

- `src/mistral_ocr_zotero/ocr_client.py` - Mistral OCR API client
  - `MistralOCRClient`: Handles PDF upload, OCR processing, and result parsing
  - `OCRResult`: Dataclass containing markdown, extracted images, tables, and metadata
  - Image header correction: Strips garbage prefix bytes before JPEG/PNG signatures

- `src/mistral_ocr_zotero/converter.py` - Enhanced PDF-to-markdown converter
  - `convert_to_markdown()`: Drop-in replacement for zotero-mcp's function
  - `convert_to_markdown_enhanced()`: Full-featured conversion with caching
  - `OCRCache`: Local file cache for OCR results

- `src/mistral_ocr_zotero/zotero_storage.py` - Zotero attachment storage
  - `ZoteroOCRStorage`: Stores OCR results as linked file attachments in Zotero
  - Uses two API clients: local (read) + web (write) since local API is read-only
  - Detects existing conversions via `[Mistral-OCR]` marker in attachment titles
  - Table inlining: Replaces `[tbl-N.md]` links with actual table content
  - Image path update: Rewrites image refs to use `images/` subdirectory
  - Storage structure: `~/.local/share/mistral-ocr-zotero/<item_key>/`
    - `<filename>_ocr.md` - Markdown with inlined tables and images/ relative paths
    - `images/` - Extracted figures (img-N.jpeg format)
    - `metadata.json` - Conversion metadata

- `src/mistral_ocr_zotero/zotero_integration.py` - Main integration layer
  - `ZoteroOCRIntegration`: Complete workflow for processing Zotero items
  - Supports `local=True` mode for faster PDF access via local Zotero API
  - `get_fulltext_with_ocr()`: Enhanced replacement for zotero-mcp get_fulltext
  - Custom exceptions: `OCRProcessingError`, `PDFDownloadError`, `FileNotAccessibleError`

- `src/mistral_ocr_zotero/pdf_chunker.py` - Large PDF partitioning
  - `PDFChunker`: analyzes PDFs and determines chunk boundaries
  - `TOCEntry`: represents a table of contents entry (level, title, page)
  - `PDFChunk`: defines a chunk (chunk_index, start_page, end_page, title)
  - `ChunkingResult`: analysis result (total_pages, chunks, has_toc, needs_chunking)
  - Uses PyMuPDF (pymupdf) for TOC extraction and PDF manipulation
  - Constants: `MAX_PAGES_PER_CHUNK = 500`, `DEFAULT_CHUNK_SIZE = 450`

- `src/mistral_ocr_zotero/chunk_merger.py` - Chunk result reconstruction
  - `ChunkMerger`: merges OCR results from multiple chunks into unified output
  - `ChunkOCRResult`: pairs a PDFChunk with its OCRResult
  - Handles page renumbering (`<!-- Page N -->` markers adjusted for continuity)
  - Prefixes image/table names (`chunk00_img-001.jpeg`) to avoid collisions
  - Adds provenance markers (`<!-- Chunk 1 of 3 (pages 1-950) -->`)

- `src/mistral_ocr_zotero/server.py` - HTTP server for Zotero plugin
  - FastAPI server on `localhost:8080`
  - REST API for triggering OCR from Zotero UI
  - Background job processing with progress tracking

### Workflow

1. When full text is requested for a Zotero item:
   - Check if a markdown conversion already exists (look for `[Mistral-OCR]` marker or local storage)
   - If no conversion exists, download PDF via local Zotero API and call Mistral OCR
   - Store result as linked file attachment + local markdown with extracted images
   - Tables are inlined, images are saved with corrected headers (Mistral returns garbage prefix)
   - Return markdown content to caller
2. Fallback to markitdown/standard extraction if Mistral API is unavailable

### Large PDF Handling (Semantic Chunking)

The Mistral OCR API has a 500-page limit per document. For larger PDFs, the system automatically partitions them at semantic boundaries (chapters/sections), processes each chunk separately, and reconstructs a unified markdown output.

**Chunking Strategy**:
1. `PDFChunker.analyze()` checks if PDF exceeds `MAX_PAGES_PER_CHUNK` (500 pages)
2. If TOC exists, chunks are split at the last chapter/section boundary before each 500-page limit
3. If no TOC, falls back to fixed-size chunks of `DEFAULT_CHUNK_SIZE` (950 pages)
4. Each chunk is extracted to a temporary PDF file via PyMuPDF's `insert_pdf()`

**Merge Strategy**:
1. Each chunk is processed independently through Mistral OCR
2. `ChunkMerger.merge()` combines results:
   - Page markers (`<!-- Page N -->`) are renumbered for continuity across chunks
   - Image names are prefixed (`chunk00_img-001.jpeg`, `chunk01_img-001.jpeg`) to avoid collisions
   - Table IDs are similarly prefixed
   - Provenance markers are added to track chunk boundaries

**Example**: A 1824-page PDF (like Sedra's Microelectronic Circuits) is split into:
- Chunk 0: pages 1-950 (or nearest chapter boundary)
- Chunk 1: pages 951-1824 (or appropriate boundaries)

### Exception Handling

The integration layer uses specific exceptions for proper error propagation:

- `OCRProcessingError`: Mistral OCR API failures (page limit exceeded, API errors, invalid PDF)
- `PDFDownloadError`: PDF download or access failures
- `FileNotAccessibleError`: Local file system access failures

The server catches these exceptions and returns the actual error message to the Zotero plugin, instead of the generic "Already processed or no PDF" message.

### Key Integration Points

- **Mistral OCR API**: `mistral-ocr-latest` model via `mistralai` SDK
- **Zotero API**: Via `pyzotero` library for item/attachment management
- **PyMuPDF (pymupdf)**: PDF analysis and chunking for large documents
- **markitdown**: Fallback PDF-to-markdown converter
- **Zotero-MCP**: Target integration point - replace `convert_to_markdown` in `client.py`

## Development Commands

Virtual environment location: `C:\Users\matti\venvs\mistral-ocr-zotero`

```bash
# Activate venv
source /c/Users/matti/venvs/mistral-ocr-zotero/Scripts/activate

# Install dependencies (using uv)
uv pip install -e ".[dev]" --python /c/Users/matti/venvs/mistral-ocr-zotero/Scripts/python.exe

# Run all tests
/c/Users/matti/venvs/mistral-ocr-zotero/Scripts/python.exe -m pytest

# Run single test
/c/Users/matti/venvs/mistral-ocr-zotero/Scripts/python.exe -m pytest tests/test_ocr_client.py::TestMistralOCRClient::test_init_with_api_key -v

# Run tests with coverage
/c/Users/matti/venvs/mistral-ocr-zotero/Scripts/python.exe -m pytest --cov=mistral_ocr_zotero

# Type checking
/c/Users/matti/venvs/mistral-ocr-zotero/Scripts/python.exe -m mypy src/

# Linting
/c/Users/matti/venvs/mistral-ocr-zotero/Scripts/python.exe -m ruff check src/
```

## Environment Variables

Copy `.env.example` to `.env` and configure:

- `MISTRAL_API_KEY`: Mistral AI API key (from console.mistral.ai)
- `ZOTERO_LIBRARY_ID`: Your Zotero library ID
- `ZOTERO_API_KEY`: Zotero API key (from zotero.org/settings/keys)
- `ZOTERO_LOCAL`: Set to `true` for local Zotero (reads PDFs via localhost:23119)
- `MISTRAL_OCR_CACHE_DIR`: Optional custom cache directory
- `OCR_SERVER_HOST`: Server host (default: 127.0.0.1)
- `OCR_SERVER_PORT`: Server port (default: 8080)

## Zotero-MCP Integration (Completed)

The integration modifies two files in zotero-mcp (`C:\Users\matti\AppData\Roaming\uv\tools\zotero-mcp\Lib\site-packages\zotero_mcp\`):

### server.py Changes

1. Added dotenv loading at startup to find `.env` files
2. Modified `get_item_fulltext()` to:
   - Check for existing OCR conversion (local storage + Zotero attachment)
   - Process PDFs with Mistral OCR if no conversion exists
   - Store results as linked file attachment with `[Mistral-OCR]` marker
   - Fall back to Zotero's cached fulltext if OCR fails

### client.py Changes

Updated `convert_to_markdown()` to use Mistral OCR with markitdown fallback.

### Installation

```bash
# Install into zotero-mcp environment
uv pip install -e "C:\Users\matti\Dev\MistralOCR_Zotero" \
  --python "C:\Users\matti\AppData\Roaming\uv\tools\zotero-mcp\Scripts\python.exe"
```

After installation, restart Claude Code for the MCP server to reload.

## Zotero Plugin

A separate Zotero plugin (`zotero-mistral-ocr`) provides a right-click context menu to trigger OCR processing directly from the Zotero UI.

**Plugin Repository**: `C:\Users\matti\Dev\zotero-mistral-ocr`

### Architecture

```
Zotero Plugin (JavaScript)  →  HTTP Server (Python FastAPI)  →  OCR Processing
     ↓                              ↓
Right-click menu            localhost:8080/ocr
Progress notifications      Background job processing
Preferences UI              API key configuration
```

### HTTP Server (this package)

- `src/mistral_ocr_zotero/server.py` - FastAPI HTTP server

#### Server Endpoints

- `GET /health` - Health check
- `POST /ocr` - Start OCR job with `{"item_keys": ["KEY1", "KEY2"], "force": false}`
- `GET /status/{job_id}` - Get job progress
- `GET /jobs` - List all jobs

#### Starting the Server

```bash
# Set environment variables
export MISTRAL_API_KEY=your-key
export ZOTERO_LOCAL=true

# Start server
mistral-ocr-server
# Or: python -m mistral_ocr_zotero.server
```

### Installing the Plugin

1. Install this package (`mistral-ocr-zotero`)
2. Build the plugin XPI from `zotero-mistral-ocr` directory
3. Install in Zotero: Tools → Add-ons → Install Add-on From File
4. Configure API key: Tools → Mistral OCR Settings

## Bug Fixes (2025-12-27)

### Linked File Attachment Filename Extraction

**Issue**: For linked file attachments in Zotero, the `filename` field is `None` (only `path` is populated like `attachments:folder/file.pdf`). This caused OCR storage to use the item key as the filename instead of the actual PDF name.

**Fix**: Updated `get_attachment_details()` in `zotero_mcp/client.py` to extract filename from the `path` field when `filename` is empty.

### Header Stacking Prevention

**Issue**: When a local OCR file exists but the Zotero attachment is missing, calling `store_ocr_result()` would add another metadata header to the existing content, causing headers to stack with each retry.

**Fix**: Added `create_attachment_only()` method to `ZoteroOCRStorage` that only creates the Zotero attachment without rewriting the local file. The `server.py` Step 1 now uses this method.

### Race Condition Protection

**Issue**: Multiple rapid requests could find local content but no Zotero attachment (due to sync delay), causing duplicate attachment creation attempts.

**Fix**: Added double-check in `create_attachment_only()` that verifies the attachment doesn't already exist before creating it.

### has_ocr_conversion Check Incomplete (Fixed 2025-12-27)

**Issue**: `has_ocr_conversion()` only checked for Zotero attachment existence, not local file storage. When Zotero attachment creation failed (e.g., API error, sync delay), subsequent calls would:
1. `has_ocr_conversion()` returns False (no Zotero attachment)
2. OCR processing runs again unnecessarily
3. `store_ocr_result()` called, potentially stacking headers

**Fix**: Updated `has_ocr_conversion()` in `zotero_storage.py` to check local storage first (`~/.local/share/mistral-ocr-zotero/<item_key>/*_ocr.md`), then fall back to Zotero attachment check. This prevents reprocessing when local files exist.

### Header Stacking Protection (Enhanced 2025-12-27)

**Issue**: Edge cases could still cause header stacking if markdown content passed to `store_ocr_result()` already contained headers. The original while-loop based stripping logic was fragile and didn't properly handle all stacked headers.

**Fix**: Replaced while-loop header stripping with robust regex-based stripping that removes ALL Mistral OCR headers in a single pass. The regex pattern matches the full header block structure including optional Source/Pages/Converted lines.

### Attachment Creation Retry Logic (Added 2025-12-27)

**Issue**: Zotero web API calls to create linked file attachments could fail silently due to network issues, rate limiting, or API errors. This left the system in an inconsistent state with local OCR files but no Zotero attachment.

**Fix**: Added retry logic with exponential backoff (1s, 2s, 4s) to both `create_attachment_only()` and `_create_linked_attachment()` methods. Up to 3 retry attempts are made before failing. Race condition checks are performed before each retry to avoid duplicate attachment creation.

### Improved Filename Fallback (Added 2025-12-27)

**Issue**: When `pdf_filename` parameter was empty or None, the attachment title would use the item key, making it less identifiable.

**Fix**: Added fallback logic in `create_attachment_only()` that extracts the base filename from the local markdown file path if no PDF filename is provided.

### ConversionResult Losing Images, Tables, and Page Count (Fixed 2025-12-27)

**Issue**: The `convert_to_markdown_enhanced()` function returned a `ConversionResult` dataclass that lacked fields for `images`, `tables`, and `pages_processed`. When the zotero-mcp `server.py` created an `OCRResult` for storage, these fields were empty. This caused:
1. **Missing images**: Images directory never created, image references not updated to `images/` prefix
2. **Missing tables**: Table content not inlined, leaving broken `[tbl-N.md]` links in markdown
3. **Incorrect metadata**: `pages_processed: 0` and `images_count: 0` in stored metadata

**Fix**:
1. Added `images`, `tables`, and `pages_processed` fields to `ConversionResult` dataclass in `converter.py`
2. Updated `convert_to_markdown_enhanced()` to populate these fields from both fresh OCR results and cached results
3. Updated `server.py` to pass `tables` to `OCRResult` constructor

**Files Changed**:
- `src/mistral_ocr_zotero/converter.py`: Added fields to `ConversionResult`, updated return statements
- `zotero_mcp/server.py`: Added `tables` parameter to `OCRResult` creation

### Write Client Using Wrong Library ID (Fixed 2025-12-27)

**Issue**: When `ZOTERO_LOCAL=true`, the `ZoteroOCRStorage` class would default `library_id` to `"0"` if the environment variable wasn't loaded in time. The local Zotero API (port 23119) accepts `"0"` as shorthand for current user, but the web API (used for writes) requires the actual library ID. This caused attachment creation to fail with `"Invalid user ID"` errors.

**Root Cause**: The code used a single `library_id` for both read and write clients:
```python
self.library_id = os.environ.get("ZOTERO_LIBRARY_ID", "0" if self.local else None)
```

**Fix**: Separated read and write library IDs in `zotero_storage.py`:
```python
read_library_id = self.library_id or ("0" if self.local else None)  # "0" OK for local reads
write_library_id = self.library_id  # Must be real ID for web API writes
```

Added explicit validation that raises `ValueError` if `write_library_id` is missing.

**Files Changed**:
- `src/mistral_ocr_zotero/zotero_storage.py`: Separated read/write library IDs, added validation

### Environment Variable Override in MCP Server (Fixed 2025-12-27)

**Issue**: The Claude Code MCP environment preset `ZOTERO_LIBRARY_ID=0` before the zotero-mcp server started. The `load_dotenv()` call didn't override existing environment variables by default, so the `.env` file value was ignored.

**Fix**: Added `override=True` to `load_dotenv()` in `zotero_mcp/server.py`:
```python
load_dotenv(_env_path, override=True)
```

**Files Changed**:
- `zotero_mcp/server.py`: Added `override=True` to force .env values to take precedence

## Known Issues

### OCR Cache Key Based on Temp Path

The `OCRCache` generates cache keys based on file path + modification time. Since PDFs are downloaded to temp directories with unique paths, the cache is never hit on subsequent requests for the same item. This causes unnecessary Mistral API calls.

**Workaround**: The local storage (`~/.local/share/mistral-ocr-zotero/<item_key>/`) is checked first, so repeated requests for the same item will use the local file without re-running OCR.

**Future Fix**: Modify cache key generation to use Zotero attachment key instead of file path.

## API Reference

See `docs/mistral_ocr_api.md` for complete Mistral OCR API documentation including:
- Endpoint specifications and parameters
- Python SDK usage patterns
- Response structure and parsing
- Pricing ($1/1000 pages) and limits (50MB max, 500 pages max per call)

**Note**: The 500-page limit is per API call. Large PDFs are automatically chunked into multiple calls (see "Large PDF Handling" section above).
