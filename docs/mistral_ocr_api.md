# Mistral OCR API Reference

Documentation compiled from official sources for the MistralOCR_Zotero project.

## Overview

Mistral OCR is an Optical Character Recognition API that comprehends document elements (text, media, tables, equations) with multimodal processing. It extracts content as ordered interleaved text and images in markdown format.

**Key Differentiator**: Native image extraction - extracts embedded images from documents along with text.

## API Specifications

### Endpoint
```
POST https://api.mistral.ai/v1/ocr
```

### Models
- `mistral-ocr-latest` - Latest stable version
- `mistral-ocr-2503` - Specific version (March 2025)
- `mistral-ocr-2512` - OCR 3 version (December 2025)

### Pricing
- $1 per 1,000 pages (standard)
- $0.50 per 1,000 pages (batch API - 50% discount)
- Performance: Up to 2,000 pages/minute on single node

### Limits
- Maximum file size: 50 MB
- Maximum pages: 1,000 per request
- Does NOT preserve: bold, underline, italics, monospace
- DOES preserve: footnotes (superscript text)

## Python SDK Usage

### Installation
```bash
pip install mistralai
```

### Process Document from URL
```python
import os
from mistralai import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

ocr_response = client.ocr.process(
    model="mistral-ocr-latest",
    document={
        "type": "document_url",
        "document_url": "https://example.com/document.pdf"
    },
    include_image_base64=True,
    table_format="markdown"  # or "html"
)
```

### Process Local PDF (Upload First)
```python
from pathlib import Path
from mistralai import Mistral
from mistralai.models import DocumentURLChunk

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
pdf_file = Path("document.pdf")

# Step 1: Upload file
uploaded_file = client.files.upload(
    file={
        "file_name": pdf_file.stem,
        "content": pdf_file.read_bytes(),
    },
    purpose="ocr",
)

# Step 2: Get signed URL
signed_url = client.files.get_signed_url(file_id=uploaded_file.id, expiry=1)

# Step 3: Process with OCR
ocr_response = client.ocr.process(
    document=DocumentURLChunk(document_url=signed_url.url),
    model="mistral-ocr-latest",
    include_image_base64=True
)
```

### Process Image from URL
```python
ocr_response = client.ocr.process(
    model="mistral-ocr-latest",
    document={
        "type": "image_url",
        "image_url": "https://example.com/image.png"
    },
    include_image_base64=True
)
```

## Request Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | string | required | Model identifier |
| `document` | Document | required | FileChunk, DocumentURLChunk, or ImageURLChunk |
| `include_image_base64` | boolean | null | Include base64 encoded images in response |
| `table_format` | "markdown" \| "html" | "markdown" | Output format for tables |
| `extract_header` | boolean | false | Extract document headers |
| `extract_footer` | boolean | false | Extract document footers |
| `pages` | array[int] | null | Specific pages to process (0-indexed) |
| `image_limit` | integer | null | Maximum images to extract |
| `image_min_size` | integer | null | Minimum image dimensions (height/width) |

## Response Structure

```python
OCRResponse:
    model: str                    # Model used
    pages: list[OCRPageObject]    # Per-page results
    usage_info: OCRUsageInfo      # Processing stats

OCRPageObject:
    index: int                    # Page number
    markdown: str                 # Extracted markdown content
    images: list[...]             # Extracted images (if include_image_base64=True)
    tables: list[...]             # Detected tables
    hyperlinks: list[...]         # Detected links
    header: str | None            # Page header (if extract_header=True)
    footer: str | None            # Page footer (if extract_footer=True)
    dimensions:
        dpi: int
        height: int
        width: int

OCRUsageInfo:
    pages_processed: int
    doc_size_bytes: int
```

## Accessing Results

```python
# Get markdown for all pages
for page in ocr_response.pages:
    print(f"Page {page.index}:")
    print(page.markdown)

    # Access extracted images
    for img in page.images:
        # img contains base64 data if include_image_base64=True
        pass

# Save single page as markdown
with open("page_0.md", "w", encoding="utf-8") as f:
    f.write(ocr_response.pages[0].markdown)
```

## Language Support

Supports thousands of scripts with >99% fuzzy match accuracy for 10+ languages including:
- Hindi, Mandarin, Arabic
- European languages (English, French, German, etc.)

## Sources

- [Mistral OCR Official Documentation](https://docs.mistral.ai/capabilities/document_ai/basic_ocr)
- [Mistral OCR API Endpoint](https://docs.mistral.ai/api/endpoint/ocr)
- [Mistral Python SDK - OCR](https://github.com/mistralai/client-python/blob/main/docs/sdks/ocr/README.md)
- [Mistral OCR Announcement](https://mistral.ai/news/mistral-ocr)
