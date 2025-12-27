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

### Key Integration Points

- **Mistral OCR API**: `mistral-ocr-latest` model via `mistralai` SDK
- **Zotero API**: Via `pyzotero` library for item/attachment management
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
uv pip install -e "C:\Users\matti\OneDrivePhD\Dev\MistralOCR_Zotero" \
  --python "C:\Users\matti\AppData\Roaming\uv\tools\zotero-mcp\Scripts\python.exe"
```

After installation, restart Claude Code for the MCP server to reload.

## Zotero Plugin

A separate Zotero plugin (`zotero-mistral-ocr`) provides a right-click context menu to trigger OCR processing directly from the Zotero UI.

**Plugin Repository**: `C:\Users\matti\OneDrivePhD\Dev\zotero-mistral-ocr`

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

## API Reference

See `docs/mistral_ocr_api.md` for complete Mistral OCR API documentation including:
- Endpoint specifications and parameters
- Python SDK usage patterns
- Response structure and parsing
- Pricing ($1/1000 pages) and limits (50MB max, 1000 pages max)
