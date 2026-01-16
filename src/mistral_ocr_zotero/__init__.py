"""
Mistral OCR Zotero Integration

Integrate Mistral OCR API with Zotero-MCP for enhanced PDF-to-markdown conversion.
"""

from mistral_ocr_zotero.ocr_client import MistralOCRClient, OCRResult
from mistral_ocr_zotero.converter import (
    convert_to_markdown,
    convert_to_markdown_enhanced,
    ConversionResult,
    OCRCache,
)
from mistral_ocr_zotero.zotero_storage import ZoteroOCRStorage, OCR_ATTACHMENT_MARKER
from mistral_ocr_zotero.zotero_integration import (
    ZoteroOCRIntegration,
    FileNotAccessibleError,
    OCRProcessingError,
    PDFDownloadError,
)
from mistral_ocr_zotero.pdf_chunker import (
    PDFChunker,
    PDFChunk,
    ChunkingResult,
    TOCEntry,
    MAX_PAGES_PER_CHUNK,
)
from mistral_ocr_zotero.chunk_merger import ChunkMerger, ChunkOCRResult

__version__ = "0.1.0"
__all__ = [
    # Core OCR client
    "MistralOCRClient",
    "OCRResult",
    # Converter functions
    "convert_to_markdown",
    "convert_to_markdown_enhanced",
    "ConversionResult",
    "OCRCache",
    # Zotero integration
    "ZoteroOCRStorage",
    "ZoteroOCRIntegration",
    "OCR_ATTACHMENT_MARKER",
    # PDF chunking
    "PDFChunker",
    "PDFChunk",
    "ChunkingResult",
    "TOCEntry",
    "MAX_PAGES_PER_CHUNK",
    # Chunk merging
    "ChunkMerger",
    "ChunkOCRResult",
    # Exceptions
    "FileNotAccessibleError",
    "OCRProcessingError",
    "PDFDownloadError",
]
