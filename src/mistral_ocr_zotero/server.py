"""
HTTP server for Mistral OCR processing.

Provides REST API endpoints for the Zotero plugin to trigger OCR processing.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load .env file from project directory or user home
for env_path in [
    Path(__file__).parent.parent.parent.parent / ".env",
    Path.home() / ".mistral-ocr-zotero" / ".env",
]:
    if env_path.exists():
        load_dotenv(env_path)
        break

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    import uvicorn
except ImportError:
    print("FastAPI and uvicorn are required. Install with: pip install fastapi uvicorn")
    sys.exit(1)

from mistral_ocr_zotero.zotero_integration import ZoteroOCRIntegration

logger = logging.getLogger(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


class JobStatus(str, Enum):
    """Status of an OCR processing job."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class JobProgress:
    """Progress tracking for an OCR job."""
    job_id: str
    status: JobStatus = JobStatus.PENDING
    total: int = 0
    completed: int = 0
    current_item: str | None = None
    errors: list[dict[str, str]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None


# In-memory job storage (simple for single-user use)
jobs: dict[str, JobProgress] = {}


# Pydantic models for API
class OCRRequest(BaseModel):
    """Request to process items with OCR."""
    item_keys: list[str]
    force: bool = False


class OCRResponse(BaseModel):
    """Response with job ID."""
    job_id: str
    items_queued: int


class StatusResponse(BaseModel):
    """Job status response."""
    job_id: str
    status: str
    total: int
    completed: int
    current_item: str | None
    errors: list[dict[str, str]]
    results: list[dict[str, Any]]


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str


# Create FastAPI app
app = FastAPI(
    title="Mistral OCR Server",
    description="HTTP server for Zotero Mistral OCR processing",
    version="0.1.0",
)

# Add CORS middleware for Zotero plugin access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local use
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_integration() -> ZoteroOCRIntegration:
    """Get or create the Zotero OCR integration instance."""
    return ZoteroOCRIntegration()


async def process_items_background(job_id: str, item_keys: list[str], force: bool) -> None:
    """Background task to process items with OCR."""
    job = jobs.get(job_id)
    if not job:
        return

    job.status = JobStatus.PROCESSING
    job.total = len(item_keys)

    try:
        integration = get_integration()

        for i, item_key in enumerate(item_keys):
            job.current_item = item_key
            logger.info(f"Processing item {i + 1}/{len(item_keys)}: {item_key}")

            try:
                result = integration.process_item(item_key, force=force)
                if result:
                    job.results.append({
                        "item_key": item_key,
                        "pages": result.pages_processed,
                        "images": len(result.images),
                        "tables": len(getattr(result, 'tables', {})),
                    })
                    logger.info(f"Completed {item_key}: {result.pages_processed} pages")
                else:
                    job.results.append({
                        "item_key": item_key,
                        "skipped": True,
                        "reason": "Already processed or no PDF",
                    })
                    logger.info(f"Skipped {item_key}")

            except Exception as e:
                error_msg = str(e)
                job.errors.append({"item_key": item_key, "error": error_msg})
                logger.error(f"Error processing {item_key}: {error_msg}")

            job.completed = i + 1

            # Small delay between items to avoid API rate limits
            if i < len(item_keys) - 1:
                await asyncio.sleep(0.5)

        job.status = JobStatus.COMPLETED if not job.errors else JobStatus.FAILED
        job.current_item = None
        job.completed_at = datetime.now()
        logger.info(f"Job {job_id} completed: {job.completed}/{job.total} items")

    except Exception as e:
        job.status = JobStatus.FAILED
        job.errors.append({"item_key": "general", "error": str(e)})
        job.completed_at = datetime.now()
        logger.error(f"Job {job_id} failed: {e}")


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="ok", version="0.1.0")


@app.post("/ocr", response_model=OCRResponse)
async def start_ocr(request: OCRRequest, background_tasks: BackgroundTasks) -> OCRResponse:
    """
    Start OCR processing for specified items.

    Args:
        request: OCR request with item keys and options.
        background_tasks: FastAPI background tasks.

    Returns:
        Response with job ID for tracking progress.
    """
    if not request.item_keys:
        raise HTTPException(status_code=400, detail="No item keys provided")

    # Create new job
    job_id = str(uuid.uuid4())[:8]
    job = JobProgress(job_id=job_id, total=len(request.item_keys))
    jobs[job_id] = job

    logger.info(f"Created job {job_id} for {len(request.item_keys)} items")

    # Start background processing
    background_tasks.add_task(
        process_items_background,
        job_id,
        request.item_keys,
        request.force,
    )

    return OCRResponse(job_id=job_id, items_queued=len(request.item_keys))


@app.get("/status/{job_id}", response_model=StatusResponse)
async def get_status(job_id: str) -> StatusResponse:
    """
    Get status of an OCR processing job.

    Args:
        job_id: The job ID returned from /ocr endpoint.

    Returns:
        Current job status and progress.
    """
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return StatusResponse(
        job_id=job.job_id,
        status=job.status.value,
        total=job.total,
        completed=job.completed,
        current_item=job.current_item,
        errors=job.errors,
        results=job.results,
    )


@app.delete("/jobs/{job_id}")
async def cancel_job(job_id: str) -> dict[str, str]:
    """Cancel a running job (removes from tracking)."""
    if job_id in jobs:
        del jobs[job_id]
        return {"status": "cancelled", "job_id": job_id}
    raise HTTPException(status_code=404, detail=f"Job {job_id} not found")


@app.get("/jobs")
async def list_jobs() -> list[dict[str, Any]]:
    """List all jobs."""
    return [
        {
            "job_id": job.job_id,
            "status": job.status.value,
            "total": job.total,
            "completed": job.completed,
            "started_at": job.started_at.isoformat(),
        }
        for job in jobs.values()
    ]


def main() -> None:
    """Run the OCR server."""
    host = os.environ.get("OCR_SERVER_HOST", "127.0.0.1")
    port = int(os.environ.get("OCR_SERVER_PORT", "8080"))

    print(f"Starting Mistral OCR Server on http://{host}:{port}")
    print("Press Ctrl+C to stop")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
