# Mistral OCR Zotero

Integrate [Mistral OCR API](https://docs.mistral.ai/capabilities/document_ai/basic_ocr) with Zotero to convert PDF documents into high-quality markdown with extracted figures, equations, and tables.

## Why?

PDF documents in Zotero libraries are difficult for LLMs to process effectively. Standard text extraction loses important structural information like tables, equations, and figure layouts. Mistral OCR provides state-of-the-art document understanding that preserves this structure in markdown format.

This project extends the Zotero-MCP `get_full_text` tool to automatically convert PDFs to markdown using Mistral OCR, storing the results alongside the original PDFs for future access.

## Features

- **Automatic PDF-to-Markdown Conversion**: Process PDFs through Mistral OCR on first access
- **Image Extraction**: Extract embedded figures and diagrams from documents
- **Table Preservation**: Maintain table structure in markdown format
- **Equation Support**: Preserve mathematical equations and formulas
- **Intelligent Caching**: Local cache prevents re-processing of already converted PDFs
- **Zotero Storage**: Store conversions as Zotero notes for persistent access
- **Fallback Support**: Automatically fall back to markitdown if Mistral OCR is unavailable
- **Batch Processing**: Convert multiple documents in a collection at once

## Installation

```bash
# Clone the repository
git clone https://github.com/mattia/mistral-ocr-zotero.git
cd mistral-ocr-zotero

# Install with uv (recommended)
uv venv /path/to/venvs/mistral-ocr-zotero
uv pip install -e ".[dev]" --python /path/to/venvs/mistral-ocr-zotero/Scripts/python.exe

# Or with pip
pip install -e ".[dev]"
```

## Configuration

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

Required environment variables:
- `MISTRAL_API_KEY`: Your Mistral AI API key ([get one here](https://console.mistral.ai/))
- `ZOTERO_LIBRARY_ID`: Your Zotero library ID
- `ZOTERO_API_KEY`: Your Zotero API key ([create here](https://www.zotero.org/settings/keys))

Optional:
- `MISTRAL_OCR_CACHE_DIR`: Custom cache directory (default: `~/.cache/mistral-ocr-zotero`)

## Usage

### Basic OCR Processing

```python
from mistral_ocr_zotero import MistralOCRClient

# Initialize client
client = MistralOCRClient()

# Process a local PDF
result = client.process_pdf_from_path("document.pdf")
print(f"Processed {result.pages_processed} pages")
print(f"Extracted {len(result.images)} images")
print(result.markdown)

# Save result with extracted images
client.save_result(result, output_dir="./output")
```

### Enhanced Converter (Drop-in Replacement)

```python
from mistral_ocr_zotero import convert_to_markdown, convert_to_markdown_enhanced

# Simple drop-in replacement for zotero-mcp
markdown = convert_to_markdown("document.pdf")

# Full-featured version with metadata
result = convert_to_markdown_enhanced(
    "document.pdf",
    use_cache=True,          # Use local cache
    fallback_to_markitdown=True,  # Fall back if API fails
)
print(f"Source: {result.source}")  # 'mistral_ocr', 'cache', or 'markitdown'
print(result.markdown)
```

### Zotero Integration

```python
from mistral_ocr_zotero import ZoteroOCRIntegration

# Initialize integration (uses environment variables)
integration = ZoteroOCRIntegration()

# Get full text with automatic OCR conversion
text = integration.get_fulltext_with_ocr(item_key="ABC12345")

# Process a specific item
result = integration.process_item("ABC12345", force=False)

# Batch process a collection
stats = integration.batch_process(
    collection_key="COLLECTION_KEY",
    limit=50,
    force=False,
)
print(f"Processed: {stats['processed']}, Skipped: {stats['skipped']}")
```

### Integrating with Zotero-MCP

To use Mistral OCR as the default converter in zotero-mcp, modify `zotero_mcp/client.py`:

```python
# Replace the existing convert_to_markdown function:
from mistral_ocr_zotero import convert_to_markdown

# The function signature is compatible - no other changes needed!
```

## Development

```bash
# Run tests
python -m pytest

# Run tests with coverage
python -m pytest --cov=mistral_ocr_zotero

# Type checking
python -m mypy src/

# Linting
python -m ruff check src/
```

## Architecture

```
src/mistral_ocr_zotero/
├── __init__.py           # Public API exports
├── ocr_client.py         # Mistral OCR API client
├── converter.py          # Enhanced converter with caching
├── zotero_storage.py     # Zotero attachment storage
└── zotero_integration.py # Main integration layer
```

### Data Flow

1. **Request**: User requests full text for a Zotero item
2. **Check Cache**: Look for existing OCR conversion (local cache or Zotero note)
3. **Download PDF**: If no cache, download PDF from Zotero
4. **Process OCR**: Send to Mistral OCR API
5. **Store Result**: Save markdown + images locally and as Zotero note
6. **Return Content**: Return markdown to caller
7. **Fallback**: If Mistral fails, use markitdown for basic extraction

## Costs

Mistral OCR pricing:
- **Standard**: $1 per 1,000 pages
- **Batch API**: $0.50 per 1,000 pages (50% discount)
- **Performance**: Up to 2,000 pages/minute

## Limitations

- Maximum file size: 50 MB per PDF
- Maximum pages: 1,000 per document
- Character formatting (bold, italic) is not preserved
- Footnotes (superscript text) are preserved

## License

MIT
