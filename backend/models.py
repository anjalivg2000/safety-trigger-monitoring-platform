"""
Safety Trigger Monitoring Platform
Pydantic Models

Models used by the FastAPI API layer.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ============================================================
# HEALTH AUTHORITY SOURCE
# ============================================================

class SourceCreate(BaseModel):
    reference_no: Optional[str] = Field(default=None, min_length=1)
    authority: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    source_type: str = "Health Authority"
    region: str = "EEA"
    monitoring_frequency: str = "Monthly"
    website: str = "EMA"
    safety_alert_type: str = "PRAC"
    url: str = Field(..., min_length=1)
    content_types: List[str] = Field(default_factory=list)
    instruction: Optional[str] = None
    active: bool = True


class SourceUpdate(BaseModel):
    reference_no: Optional[str] = Field(None, min_length=1)
    authority: Optional[str] = Field(None, min_length=1)
    name: Optional[str] = Field(None, min_length=1)
    source_type: Optional[str] = Field(None, min_length=1)
    region: Optional[str] = Field(None, min_length=1)
    monitoring_frequency: Optional[str] = Field(None, min_length=1)
    website: Optional[str] = Field(None, min_length=1)
    safety_alert_type: Optional[str] = Field(None, min_length=1)
    url: Optional[str] = Field(None, min_length=1)
    content_types: Optional[List[str]] = None
    instruction: Optional[str] = None
    active: Optional[bool] = None
    automatic_monitoring: Optional[bool] = None


class SourceResponse(BaseModel):
    id: int
    reference_no: Optional[str] = None
    authority: str
    name: str
    source_type: Optional[str] = None
    region: str = "EEA"
    monitoring_frequency: str = "Monthly"
    website: str = "EMA"
    safety_alert_type: Optional[str] = None
    url: str
    content_types: List[str] = Field(default_factory=list)
    instruction: Optional[str] = None
    active: bool
    last_crawled_at: Optional[str] = None
    last_crawl_status: Optional[str] = None
    last_error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ProductClassCreate(BaseModel):
    reference_no: Optional[str] = Field(default=None, min_length=1)
    class_name: str = Field(..., min_length=1)
    active: bool = True


class ProductClassUpdate(BaseModel):
    reference_no: Optional[str] = Field(None, min_length=1)
    class_name: Optional[str] = Field(None, min_length=1)
    active: Optional[bool] = None


class ProductClassResponse(BaseModel):
    id: int
    reference_no: str
    class_name: str
    active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    products: List["ProductResponse"] = Field(default_factory=list)


class ProductCreate(BaseModel):
    product_class_id: int
    reference_no: Optional[str] = Field(default=None, min_length=1)
    product_name: str = Field(..., min_length=1)
    active: bool = True


class ProductUpdate(BaseModel):
    product_class_id: Optional[int] = None
    reference_no: Optional[str] = Field(None, min_length=1)
    product_name: Optional[str] = Field(None, min_length=1)
    active: Optional[bool] = None


class ProductResponse(BaseModel):
    id: int
    product_class_id: int
    reference_no: str
    product_name: str
    active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SourceTestRequest(BaseModel):
    url: str = Field(..., min_length=1)
    content_types: Optional[List[str]] = None


class SourceTestResponse(BaseModel):
    url: str
    http_status: Optional[int] = None
    section_found: bool = False
    meeting_links_found: int = 0
    pdf_links_found: int = 0
    status: str
    error: Optional[str] = None


# ============================================================
# CRAWL & MONITOR
# ============================================================

class CrawlDiscoverRequest(BaseModel):
    source_id: int
    content_types: Optional[List[str]] = None


class CrawlProcessRequest(BaseModel):
    source_id: int
    document_url: str = Field(..., min_length=1)
    title: Optional[str] = None
    filename: Optional[str] = None
    meeting_date: Optional[str] = None
    publication_date: Optional[str] = None
    content_type: Optional[str] = None
    reference_id: Optional[str] = None


# ============================================================
# DOCUMENTS
# ============================================================

class DocumentResponse(BaseModel):
    id: int
    source_id: int
    title: Optional[str] = None
    url: str
    meeting_date: Optional[str] = None
    publication_date: Optional[str] = None
    filename: Optional[str] = None
    discovered_date: Optional[str] = None
    sha256: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[str] = None


class DocumentPageResponse(BaseModel):
    id: int
    document_id: int
    page_number: int
    page_text: str
    created_at: Optional[str] = None


# ============================================================
# SAFETY FINDINGS
# ============================================================

class FindingResponse(BaseModel):
    id: int
    document_id: int
    page_number: Optional[int] = None

    product_name: Optional[str] = None

    active_substance: Optional[str] = None

    trigger_name: Optional[str] = None

    safety_topic: Optional[str] = None

    relevant_terms: Optional[str] = None

    evidence: Optional[str] = None

    section: Optional[str] = None

    comparison_status: Optional[str] = None

    evidence_hash: Optional[str] = None

    created_at: Optional[str] = None


class EvidenceDetailResponse(BaseModel):
    exact_text: Optional[str] = None
    evidence_hash: Optional[str] = None
    document_id: int
    page_number: Optional[int] = None
    page_text: Optional[str] = None
    document_title: Optional[str] = None
    document_url: Optional[str] = None
    filename: Optional[str] = None
    warning: Optional[str] = None


# ============================================================
# AI SUMMARY
# ============================================================

class SummaryResponse(BaseModel):
    id: int
    finding_id: int

    product_name: Optional[str] = None

    active_substance: Optional[str] = None

    safety_topic: Optional[str] = None

    prac_assessment: Optional[str] = None

    outcome: Optional[str] = None

    summary: Optional[str] = None

    model: Optional[str] = None

    created_at: Optional[str] = None

    status: Optional[str] = None


# ============================================================
# REVIEW
# ============================================================

class ReviewCreate(BaseModel):
    finding_id: int

    stage: Literal["INITIAL", "FINAL"] = "INITIAL"

    reviewer: str = Field(
        default="PV Reviewer",
        min_length=1,
    )

    decision: str = Field(
        ...,
        min_length=1,
    )

    comments: Optional[str] = None


class ReviewUpdate(BaseModel):
    stage: Literal["INITIAL", "FINAL"] = "INITIAL"

    reviewer: str = Field(
        default="PV Reviewer",
        min_length=1,
    )

    decision: str = Field(
        ...,
        min_length=1,
    )

    comments: Optional[str] = None


class ReviewResponse(BaseModel):
    id: int

    finding_id: int

    stage: str = "INITIAL"

    reviewer: str

    decision: str

    comments: Optional[str] = None

    reviewed_at: Optional[str] = None


# ============================================================
# TRIGGER CONFIGURATION
# ============================================================

class TriggerConfig(BaseModel):
    name: str

    type: str = "Effect Based"

    active: bool = True

    substances: List[str] = Field(
        default_factory=list
    )

    safety_terms: List[str] = Field(
        default_factory=list
    )


# ============================================================
# MONITORING
# ============================================================

class MonitoringRunResponse(BaseModel):
    job_id: str

    status: str

    progress: int = 0

    message: Optional[str] = None

    created_at: Optional[str] = None


class MonitoringStatusResponse(BaseModel):
    job_id: str

    status: str

    progress: int = 0

    message: Optional[str] = None

    created_at: Optional[str] = None

    result: Optional[Dict[str, Any]] = None

    error: Optional[str] = None


# ============================================================
# CRAWL HISTORY
# ============================================================

class CrawlHistoryResponse(BaseModel):
    id: int

    source_id: Optional[int] = None

    started_at: Optional[str] = None

    completed_at: Optional[str] = None

    status: Optional[str] = None

    documents_found: int = 0

    error_message: Optional[str] = None


# ============================================================
# EXTRACTION HISTORY
# ============================================================

class ExtractionHistoryResponse(BaseModel):
    id: int

    document_id: Optional[int] = None

    started_at: Optional[str] = None

    completed_at: Optional[str] = None

    status: Optional[str] = None

    pages_extracted: int = 0

    error_message: Optional[str] = None


# ============================================================
# DASHBOARD
# ============================================================

class DashboardResponse(BaseModel):
    sources: int = 0

    documents: int = 0

    processed_documents: int = 0

    findings: int = 0

    new_information: int = 0

    pending_reviews: int = 0

    completed_reviews: int = 0

    reviews: int = 0

    summaries: int = 0

    latest_crawl: Optional[Dict[str, Any]] = None


# ============================================================
# API GENERIC RESPONSE
# ============================================================

class APIResponse(BaseModel):
    status: str

    message: Optional[str] = None

    data: Optional[Any] = None


# ============================================================
# OLLAMA
# ============================================================

class OllamaTestResponse(BaseModel):
    status: str

    message: Optional[str] = None

    model: Optional[str] = None

    base_url: Optional[str] = None

    error: Optional[str] = None


# ============================================================
# SUMMARY GENERATION REQUEST
# ============================================================

class SummaryGenerateRequest(BaseModel):
    finding_id: int


class DocumentAIAnalysisRequest(BaseModel):
    provider: str
    analysis_type: str = "summary"


# ============================================================
# PDF DOWNLOAD
# ============================================================

class PDFDownloadResponse(BaseModel):
    document_id: int

    filename: str

    status: str

    message: Optional[str] = None


# ============================================================
# COMPLETE FINDING VIEW
# ============================================================

class FindingDetailResponse(BaseModel):
    finding: Optional[FindingResponse] = None

    document: Optional[DocumentResponse] = None

    summary: Optional[SummaryResponse] = None

    pages: List[DocumentPageResponse] = Field(
        default_factory=list
    )

    reviews: List[ReviewResponse] = Field(
        default_factory=list
    )


# ============================================================
# HISTORY RESPONSE
# ============================================================

class HistoryResponse(BaseModel):

    crawl_history: List[CrawlHistoryResponse] = Field(
        default_factory=list
    )

    extraction_history: List[ExtractionHistoryResponse] = Field(
        default_factory=list
    )

    review_history: List[ReviewResponse] = Field(
        default_factory=list
    )


# ============================================================
# MONITORING RESULT
# ============================================================

class MonitoringResult(BaseModel):

    new_documents: int = 0

    processed_documents: int = 0

    new_findings: int = 0

    new_information: int = 0

    summaries_generated: int = 0

    skipped_documents: int = 0

    failed_documents: int = 0


# ============================================================
# COMPLETE SAFETY SUMMARY
# ============================================================

class SafetySummary(BaseModel):

    product_name: Optional[str] = None

    active_substance: Optional[str] = None

    safety_topic: Optional[str] = None

    prac_assessment: Optional[str] = None

    outcome: Optional[str] = None

    summary: Optional[str] = None

    evidence: Optional[str] = None

    source_document: Optional[str] = None

    page_number: Optional[int] = None

    model: Optional[str] = None

    status: str = "PENDING_REVIEW"


# ============================================================
# HEALTH CHECK
# ============================================================

class HealthResponse(BaseModel):

    status: str

    application: str

    database: str

    timestamp: Optional[str] = None