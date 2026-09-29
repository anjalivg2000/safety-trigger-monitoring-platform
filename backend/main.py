import logging
import json
import os
import uuid
import re
import sys
import fitz
from html import escape as html_escape
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib import colors

if __package__ in (None, ""):
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from backend.database import get_db, init_db
    from backend.models import (
        SourceCreate,
        SourceUpdate,
        SourceResponse,
        ProductClassCreate,
        ProductClassUpdate,
        ProductClassResponse,
        ProductCreate,
        ProductUpdate,
        ProductResponse,
        SourceTestRequest,
        CrawlDiscoverRequest,
        CrawlProcessRequest,
        DocumentResponse,
        DocumentPageResponse,
        FindingResponse,
        SummaryResponse,
        ReviewCreate,
        ReviewUpdate,
        ReviewResponse,
        TriggerConfig,
    )
    from backend.crawler import (
        DEFAULT_SOURCE_CONFIGS,
        EMAPRAC_URL,
        crawl_source,
        discover_meeting_pdfs,
        download_pdf,
        classify_content_type,
        normalize_content_types,
        test_source,
    )
    from backend.product_config import DEFAULT_PRODUCT_CLASSES
    from backend.pdf_processor import (
        process_pdf_safe,
        get_pdf_metadata,
    )
    from backend.detector import (
        detect_document,
        load_trigger_config,
    )
    from backend.comparator import (
        compare_finding,
        remove_duplicate_findings,
    )
    from backend.ollama_client import (
        generate_summary_from_finding,
        test_ollama_connection,
    )
    from backend.topic_extractor import (
        extract_meeting_topics,
        extract_section_summaries,
    )
else:
    from .database import get_db, init_db
    from .models import (
        SourceCreate,
        SourceUpdate,
        SourceResponse,
        ProductClassCreate,
        ProductClassUpdate,
        ProductClassResponse,
        ProductCreate,
        ProductUpdate,
        ProductResponse,
        SourceTestRequest,
        CrawlDiscoverRequest,
        CrawlProcessRequest,
        DocumentResponse,
        DocumentPageResponse,
        FindingResponse,
        SummaryResponse,
        ReviewCreate,
        ReviewUpdate,
        ReviewResponse,
        TriggerConfig,
    )
    from .crawler import (
        DEFAULT_SOURCE_CONFIGS,
        EMAPRAC_URL,
        crawl_source,
        discover_meeting_pdfs,
        download_pdf,
        classify_content_type,
        normalize_content_types,
        test_source,
    )
    from .product_config import DEFAULT_PRODUCT_CLASSES
    from .pdf_processor import (
        process_pdf_safe,
        get_pdf_metadata,
    )
    from .detector import (
        detect_document,
        load_trigger_config,
    )
    from .comparator import (
        compare_finding,
        remove_duplicate_findings,
    )
    from .ollama_client import (
        generate_summary_from_finding,
        test_ollama_connection,
    )
    from .topic_extractor import (
        extract_meeting_topics,
        extract_section_summaries,
    )

# ---------------------------------------------------------
# Logging
# ---------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("safety-trigger-poc")

# ---------------------------------------------------------
# Paths
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
PDF_DIR = BASE_DIR / "data" / "pdfs"
SUMMARY_DIR = BASE_DIR / "data" / "summaries"

SUMMARY_DIR.mkdir(
    parents=True,
    exist_ok=True
)

PRAC_SECTION_XPATH = "//h2[normalize-space()='PRAC minutes']"

PRAC_MEETING_XPATH = (
    "//a[contains(@href, "
    "'/documents/minutes/minutes-prac-meeting-')]"
)
PDF_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------
# FastAPI
# ---------------------------------------------------------

app = FastAPI(
    title="Safety Trigger POC",
    description="EMA PRAC Safety Trigger Monitoring POC",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# Startup
# ---------------------------------------------------------

@app.on_event("startup")
def startup():
    logger.info("Initializing database...")
    init_db()

    with get_db() as conn:
        for source_config in DEFAULT_SOURCE_CONFIGS:
            reference_no = source_config["reference_no"]
            url = source_config["url"]

            existing = conn.execute(
                """
                SELECT id FROM sources
                WHERE reference_no = ? OR url = ?
                LIMIT 1
                """,
                (reference_no, url),
            ).fetchone()

            payload = {
                "reference_no": reference_no,
                "authority": "European Medicines Agency",
                "name": source_config["name"],
                "source_type": source_config["source_type"],
                "region": source_config["region"],
                "monitoring_frequency": source_config["monitoring_frequency"],
                "website": source_config["website"],
                "safety_alert_type": source_config["safety_alert_type"],
                "url": url,
                "content_types": source_config["content_types"],
                "instruction": source_config.get("instruction", ""),
                "active": int(bool(source_config.get("active", True))),
                "updated_at": datetime.utcnow().isoformat(),
            }

            if existing:
                conn.execute(
                    """
                    UPDATE sources
                    SET reference_no = ?,
                        authority = ?,
                        name = ?,
                        source_type = ?,
                        region = ?,
                        monitoring_frequency = ?,
                        website = ?,
                        safety_alert_type = ?,
                        url = ?,
                        content_types = ?,
                        instruction = ?,
                        active = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        payload["reference_no"],
                        payload["authority"],
                        payload["name"],
                        payload["source_type"],
                        payload["region"],
                        payload["monitoring_frequency"],
                        payload["website"],
                        payload["safety_alert_type"],
                        payload["url"],
                        json.dumps(payload["content_types"]),
                        payload["instruction"],
                        payload["active"],
                        payload["updated_at"],
                        existing["id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO sources
                    (
                        reference_no,
                        authority,
                        name,
                        source_type,
                        region,
                        monitoring_frequency,
                        website,
                        safety_alert_type,
                        url,
                        content_types,
                        instruction,
                        active,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload["reference_no"],
                        payload["authority"],
                        payload["name"],
                        payload["source_type"],
                        payload["region"],
                        payload["monitoring_frequency"],
                        payload["website"],
                        payload["safety_alert_type"],
                        payload["url"],
                        json.dumps(payload["content_types"]),
                        payload["instruction"],
                        payload["active"],
                        datetime.utcnow().isoformat(),
                        payload["updated_at"],
                    ),
                )

        for class_config in DEFAULT_PRODUCT_CLASSES:
            class_reference = class_config["reference_no"]
            existing_class = conn.execute(
                "SELECT id FROM product_classes WHERE reference_no = ? LIMIT 1",
                (class_reference,),
            ).fetchone()

            class_payload = {
                "reference_no": class_reference,
                "class_name": class_config["name"],
                "active": int(bool(class_config.get("active", True))),
                "updated_at": datetime.utcnow().isoformat(),
            }

            if existing_class:
                conn.execute(
                    """
                    UPDATE product_classes
                    SET reference_no = ?,
                        class_name = ?,
                        active = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        class_payload["reference_no"],
                        class_payload["class_name"],
                        class_payload["active"],
                        class_payload["updated_at"],
                        existing_class["id"],
                    ),
                )
                class_id = existing_class["id"]
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO product_classes
                    (reference_no, class_name, active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        class_payload["reference_no"],
                        class_payload["class_name"],
                        class_payload["active"],
                        datetime.utcnow().isoformat(),
                        class_payload["updated_at"],
                    ),
                )
                class_id = cursor.lastrowid

            for product_index, product_name in enumerate(class_config["products"], start=1):
                product_reference = f"{class_reference}_P{product_index:03d}"
                existing_product = conn.execute(
                    "SELECT id FROM products WHERE reference_no = ? LIMIT 1",
                    (product_reference,),
                ).fetchone()

                payload = {
                    "product_class_id": class_id,
                    "reference_no": product_reference,
                    "product_name": product_name,
                    "active": 1,
                    "updated_at": datetime.utcnow().isoformat(),
                }

                if existing_product:
                    conn.execute(
                        """
                        UPDATE products
                        SET product_class_id = ?,
                            reference_no = ?,
                            product_name = ?,
                            active = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            payload["product_class_id"],
                            payload["reference_no"],
                            payload["product_name"],
                            payload["active"],
                            payload["updated_at"],
                            existing_product["id"],
                        ),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO products
                        (product_class_id, reference_no, product_name, active, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            payload["product_class_id"],
                            payload["reference_no"],
                            payload["product_name"],
                            payload["active"],
                            datetime.utcnow().isoformat(),
                            payload["updated_at"],
                        ),
                    )

    logger.info("Default EMA source configuration loaded.")
    logger.info("Default product configuration loaded.")


# ---------------------------------------------------------
# Frontend
# ---------------------------------------------------------

if FRONTEND_DIR.exists():
    app.mount(
        "/frontend",
        StaticFiles(directory=str(FRONTEND_DIR)),
        name="frontend",
    )


@app.get("/app.js", include_in_schema=False)
def serve_app_js():
    app_js = FRONTEND_DIR / "app.js"
    if not app_js.exists():
        raise HTTPException(status_code=404, detail="frontend/app.js not found")
    return FileResponse(
        app_js,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/style.css", include_in_schema=False)
def serve_style_css():
    css_file = FRONTEND_DIR / "style.css"
    if not css_file.exists():
        raise HTTPException(status_code=404, detail="frontend/style.css not found")
    return FileResponse(
        css_file,
        media_type="text/css",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/", include_in_schema=False)
def root():
    index_file = FRONTEND_DIR / "index.html"

    if not index_file.exists():
        return {
            "status": "ok",
            "message": "Safety Trigger POC backend is running.",
        }

    return FileResponse(index_file)


# ---------------------------------------------------------
# Health
# ---------------------------------------------------------

@app.get("/api/health")
def health():
    return {
        "status": "healthy",
        "application": "Safety Trigger POC",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------
# Dashboard
# ---------------------------------------------------------

@app.get("/api/dashboard")
def dashboard():
    with get_db() as conn:
        documents = conn.execute(
            "SELECT COUNT(*) AS count FROM documents"
        ).fetchone()["count"]

        processed_documents = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM documents
            WHERE UPPER(COALESCE(status, '')) IN ('PROCESSED', 'EXTRACTED')
            """
        ).fetchone()["count"]

        findings = conn.execute(
            "SELECT COUNT(*) AS count FROM findings"
        ).fetchone()["count"]

        new_information = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM findings
            WHERE UPPER(COALESCE(comparison_status, ''))
                IN ('NEW', 'NEW_INFORMATION')
            """
        ).fetchone()["count"]

        pending_reviews = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM findings f
            WHERE NOT EXISTS (
                SELECT 1
                FROM reviews r
                WHERE r.finding_id = f.id
            )
            """
        ).fetchone()["count"]

        completed_reviews = conn.execute(
            """
            SELECT COUNT(DISTINCT finding_id) AS count
            FROM reviews
            """
        ).fetchone()["count"]

        review_records = conn.execute(
            "SELECT COUNT(*) AS count FROM reviews"
        ).fetchone()["count"]

        sources = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM sources
            WHERE active = 1
            """
        ).fetchone()["count"]

        summaries = conn.execute(
            "SELECT COUNT(*) AS count FROM summaries"
        ).fetchone()["count"]

        latest_crawl = conn.execute(
            """
            SELECT
                ch.id,
                ch.source_id,
                ch.started_at,
                ch.completed_at,
                ch.status,
                ch.documents_found,
                ch.error_message,
                s.authority,
                s.name AS source_name,
                s.url AS source_url
            FROM crawl_history ch
            LEFT JOIN sources s
                ON s.id = ch.source_id
            ORDER BY ch.id DESC
            LIMIT 1
            """
        ).fetchone()

    return {
        "sources": sources,
        "documents": documents,
        "processed_documents": processed_documents,
        "findings": findings,
        "new_information": new_information,
        "pending_reviews": pending_reviews,
        "completed_reviews": completed_reviews,
        "reviews": review_records,
        "summaries": summaries,
        "latest_crawl": dict(latest_crawl) if latest_crawl else None,
    }


# ---------------------------------------------------------
# Sources
# ---------------------------------------------------------

def serialize_source_row(row):
    data = dict(row)
    data["content_types"] = normalize_content_types(data.get("content_types"))
    data["reference_no"] = data.get("reference_no") or data.get("id")
    return data


@app.get("/api/sources")
def list_sources():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM sources
            ORDER BY id
            """
        ).fetchall()

    return [serialize_source_row(row) for row in rows]


@app.post("/api/sources")
def create_source(source: SourceCreate):
    now = datetime.utcnow().isoformat()
    reference_no = source.reference_no or f"{source.website.upper()}_{source.name.strip().upper().replace(' ', '_')[:12]}_001"

    try:
        with get_db() as conn:
            existing = conn.execute(
                "SELECT id FROM sources WHERE reference_no = ? OR url = ? LIMIT 1",
                (reference_no, str(source.url)),
            ).fetchone()

            if existing:
                raise HTTPException(
                    status_code=400,
                    detail="A source with this reference number or URL already exists.",
                )

            cursor = conn.execute(
                """
                INSERT INTO sources
                (
                    reference_no,
                    authority,
                    name,
                    source_type,
                    region,
                    monitoring_frequency,
                    website,
                    safety_alert_type,
                    url,
                    content_types,
                    active,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reference_no,
                    source.authority,
                    source.name,
                    source.source_type,
                    source.region,
                    source.monitoring_frequency,
                    source.website,
                    source.safety_alert_type,
                    str(source.url),
                    json.dumps(source.content_types),
                    source.active,
                    now,
                    now,
                ),
            )

            source_id = cursor.lastrowid

        return {
            "success": True,
            "id": source_id,
            "message": "Source created successfully.",
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to create source")
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )


@app.patch("/api/sources/{source_id}")
def update_source(source_id: int, source: SourceUpdate):
    updates = source.dict(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No source fields supplied.")

    if "content_types" in updates:
        updates["content_types"] = json.dumps(updates["content_types"])

    updates["updated_at"] = datetime.utcnow().isoformat()
    assignments = ", ".join(f"{field} = ?" for field in updates)
    values = list(updates.values()) + [source_id]

    try:
        with get_db() as conn:
            cursor = conn.execute(
                f"UPDATE sources SET {assignments} WHERE id = ?",
                values,
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Source not found.")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update source")
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "success": True,
        "id": source_id,
        "message": "Source updated successfully.",
    }


@app.post("/api/sources/test")
def test_source_endpoint(request: SourceTestRequest):
    try:
        result = test_source(str(request.url))

        return {
            "success": str(result.get("status", "")).upper() == "SUCCESS",
            **result,
        }

    except Exception as exc:
        logger.exception("Source test failed")
        return {
            "success": False,
            "status": "error",
            "message": str(exc),
        }


@app.get("/api/product-classes")
def list_product_classes():
    with get_db() as conn:
        classes = conn.execute(
            "SELECT * FROM product_classes ORDER BY id"
        ).fetchall()

        rows = []
        for item in classes:
            products = conn.execute(
                "SELECT * FROM products WHERE product_class_id = ? ORDER BY id",
                (item["id"],),
            ).fetchall()

            rows.append({
                "id": item["id"],
                "reference_no": item["reference_no"],
                "class_name": item["class_name"],
                "active": bool(item["active"]),
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
                "products": [
                    {
                        "id": product["id"],
                        "product_class_id": product["product_class_id"],
                        "reference_no": product["reference_no"],
                        "product_name": product["product_name"],
                        "active": bool(product["active"]),
                        "created_at": product["created_at"],
                        "updated_at": product["updated_at"],
                    }
                    for product in products
                ],
            })

    return rows


@app.post("/api/product-classes")
def create_product_class(payload: ProductClassCreate):
    reference_no = payload.reference_no or f"PROD_CLASS_{payload.class_name.upper().replace(' ', '_')[:24]}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    now = datetime.utcnow().isoformat()

    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM product_classes WHERE reference_no = ? LIMIT 1",
            (reference_no,),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="A product class with this reference already exists.")

        cursor = conn.execute(
            """
            INSERT INTO product_classes
            (reference_no, class_name, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (reference_no, payload.class_name, int(bool(payload.active)), now, now),
        )
        class_id = cursor.lastrowid

    return {"success": True, "id": class_id, "reference_no": reference_no, "message": "Product class created successfully."}


@app.patch("/api/product-classes/{class_id}")
def update_product_class(class_id: int, payload: ProductClassUpdate):
    updates = payload.dict(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No product class fields supplied.")

    if "active" in updates:
        updates["active"] = int(bool(updates["active"]))

    updates["updated_at"] = datetime.utcnow().isoformat()
    assignments = ", ".join(f"{field} = ?" for field in updates)
    values = list(updates.values()) + [class_id]

    with get_db() as conn:
        cursor = conn.execute(
            f"UPDATE product_classes SET {assignments} WHERE id = ?",
            values,
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Product class not found.")

    return {"success": True, "id": class_id, "message": "Product class updated successfully."}


@app.post("/api/products")
def create_product(payload: ProductCreate):
    now = datetime.utcnow().isoformat()
    reference_no = payload.reference_no or f"PROD_{payload.product_class_id}_{payload.product_name.upper().replace(' ', '_')[:20]}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM products WHERE reference_no = ? LIMIT 1",
            (reference_no,),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="A product with this reference already exists.")

        class_exists = conn.execute(
            "SELECT id FROM product_classes WHERE id = ? LIMIT 1",
            (payload.product_class_id,),
        ).fetchone()
        if not class_exists:
            raise HTTPException(status_code=404, detail="Product class not found.")

        cursor = conn.execute(
            """
            INSERT INTO products
            (product_class_id, reference_no, product_name, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.product_class_id,
                reference_no,
                payload.product_name,
                int(bool(payload.active)),
                now,
                now,
            ),
        )
        product_id = cursor.lastrowid

    return {"success": True, "id": product_id, "reference_no": reference_no, "message": "Product created successfully."}


@app.patch("/api/products/{product_id}")
def update_product(product_id: int, payload: ProductUpdate):
    updates = payload.dict(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No product fields supplied.")

    if "active" in updates:
        updates["active"] = int(bool(updates["active"]))

    updates["updated_at"] = datetime.utcnow().isoformat()
    assignments = ", ".join(f"{field} = ?" for field in updates)
    values = list(updates.values()) + [product_id]

    with get_db() as conn:
        cursor = conn.execute(
            f"UPDATE products SET {assignments} WHERE id = ?",
            values,
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Product not found.")

    return {"success": True, "id": product_id, "message": "Product updated successfully."}


@app.delete("/api/product-classes/{class_id}")
def delete_product_class(class_id: int):
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE product_classes SET active = 0, updated_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), class_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Product class not found.")

    return {"success": True, "id": class_id, "message": "Product class deactivated."}


@app.delete("/api/products/{product_id}")
def delete_product(product_id: int):
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE products SET active = 0, updated_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), product_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Product not found.")

    return {"success": True, "id": product_id, "message": "Product deactivated."}


# ---------------------------------------------------------
# Crawl & Monitor
# ---------------------------------------------------------

def _published_date_token(value: Optional[str]) -> str:
    if not value:
        return "UNDATED"

    cleaned = " ".join(str(value).split())
    for date_format in (
        "%Y-%m-%d",
        "%d %B %Y",
        "%d %b %Y",
        "%d-%B-%Y",
        "%d-%b-%Y",
    ):
        try:
            return datetime.strptime(cleaned, date_format).strftime("%Y%m%d")
        except ValueError:
            continue

    match = re.search(r"\b(\d{1,2})[\s-]+([A-Za-z]{3,9})[\s-]+(\d{4})\b", cleaned)
    if match:
        for date_format in ("%d %B %Y", "%d %b %Y"):
            try:
                parsed = datetime.strptime(" ".join(match.groups()), date_format)
                return parsed.strftime("%Y%m%d")
            except ValueError:
                continue

    return "UNDATED"


def _document_reference_id(source_reference: Optional[str], published_date: Optional[str], document_id: int) -> str:
    prefix = re.sub(
        r"[^A-Za-z0-9_-]+",
        "_",
        str(source_reference or "DOCUMENT").strip(),
    ).strip("_")
    return f"{prefix}_{_published_date_token(published_date)}_{document_id:03d}"


def _record_discovered_documents(
    source: dict,
    documents: list[dict],
) -> tuple[int, str]:
    crawled_at = datetime.utcnow().isoformat()
    source_reference = source.get("reference_no") or str(source["id"])

    with get_db() as conn:
        for document in documents:
            url = str(document.get("document_key") or document.get("url") or "").strip()
            parsed_url = urlparse(url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                logger.warning("Skipping discovered document with invalid URL: %s", url)
                continue

            publication_date = document.get("publication_date")
            existing = conn.execute(
                """
                SELECT id, reference_id, publication_date
                FROM documents
                WHERE lower(rtrim(url, '/')) = lower(rtrim(?, '/'))
                LIMIT 1
                """,
                (url,),
            ).fetchone()

            is_new = existing is None
            if existing:
                document_id = int(existing["id"])
                conn.execute(
                    """
                    UPDATE documents
                    SET title = COALESCE(?, title),
                        publication_date = ?,
                        meeting_date = COALESCE(?, meeting_date),
                        filename = COALESCE(?, filename),
                        content_type = COALESCE(?, content_type),
                        last_crawled_at = ?
                    WHERE id = ?
                    """,
                    (
                        document.get("title"),
                        publication_date,
                        document.get("meeting_date"),
                        document.get("filename"),
                        document.get("content_type"),
                        crawled_at,
                        document_id,
                    ),
                )
                reference_id = existing["reference_id"]
                previous_generated_id = _document_reference_id(
                    source_reference,
                    existing["publication_date"],
                    document_id,
                )
                refreshed_reference_id = _document_reference_id(
                    source_reference,
                    publication_date,
                    document_id,
                )
                if not reference_id or reference_id == previous_generated_id:
                    reference_id = refreshed_reference_id
                    conn.execute(
                        "UPDATE documents SET reference_id = ? WHERE id = ?",
                        (reference_id, document_id),
                    )
            else:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO documents
                    (
                        source_id,
                        title,
                        url,
                        meeting_date,
                        publication_date,
                        filename,
                        discovered_date,
                        last_crawled_at,
                        content_type,
                        status,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'NEW', ?)
                    """,
                    (
                        int(source["id"]),
                        document.get("title") or document.get("filename") or url,
                        url,
                        document.get("meeting_date"),
                        publication_date,
                        document.get("filename"),
                        crawled_at,
                        crawled_at,
                        document.get("content_type"),
                        crawled_at,
                    ),
                )
                if cursor.rowcount:
                    document_id = int(cursor.lastrowid)
                    reference_id = None
                else:
                    existing = conn.execute(
                        """
                        SELECT id, reference_id, publication_date
                        FROM documents
                        WHERE lower(rtrim(url, '/')) = lower(rtrim(?, '/'))
                        LIMIT 1
                        """,
                        (url,),
                    ).fetchone()
                    if not existing:
                        raise RuntimeError(
                            f"Discovered document could not be stored: {url}"
                        )
                    document_id = int(existing["id"])
                    reference_id = existing["reference_id"]
                    is_new = False
                    conn.execute(
                        """
                        UPDATE documents
                        SET publication_date = ?,
                            content_type = COALESCE(?, content_type),
                            last_crawled_at = ?
                        WHERE id = ?
                        """,
                        (
                            publication_date,
                            document.get("content_type"),
                            crawled_at,
                            document_id,
                        ),
                    )

            if not reference_id:
                reference_id = _document_reference_id(
                    source_reference,
                    publication_date,
                    document_id,
                )
                conn.execute(
                    "UPDATE documents SET reference_id = ? WHERE id = ?",
                    (reference_id, document_id),
                )

            document.update(
                {
                    "id": document_id,
                    "reference_id": reference_id,
                    "publication_date": publication_date,
                    "date_crawled": crawled_at,
                    "status": "NEW" if is_new else "ALREADY_CRAWLED",
                    "new_document": is_new,
                }
            )

        conn.execute(
            """
            UPDATE sources
            SET last_crawled_at = ?,
                last_crawl_status = 'success',
                last_error_message = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (crawled_at, crawled_at, int(source["id"])),
        )

    return sum(1 for document in documents if document.get("new_document")), crawled_at


@app.post("/api/crawl/discover")
def discover_crawl_documents(request: CrawlDiscoverRequest):
    with get_db() as conn:
        source = conn.execute(
            """
            SELECT *
            FROM sources
            WHERE id = ?
              AND active = 1
            """,
            (request.source_id,),
        ).fetchone()

    if not source:
        raise HTTPException(
            status_code=404,
            detail="Active source not found.",
        )

    try:
        source_data = serialize_source_row(source)
        result = crawl_source(
            source_url=str(source["url"]),
            source_id=int(request.source_id),
            content_types=source_data.get("content_types") or [source_data.get("safety_alert_type")],
            source_name=source_data.get("name"),
            reference_no=source_data.get("reference_no"),
        )
    except Exception as exc:
        logger.exception(
            "Document discovery failed for source %s",
            request.source_id,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Document discovery failed: {exc}",
        )

    if not result["success"]:
        raise HTTPException(
            status_code=502,
            detail=f"Document discovery failed: {result.get('error') or 'Unknown crawl failure'}",
        )

    new_documents, crawled_at = _record_discovered_documents(
        source_data,
        result.get("documents", []),
    )

    return {
        "status": "success",
        "source": source_data,
        "documents_found": len(result.get("documents", [])),
        "new_documents": new_documents,
        "date_crawled": crawled_at,
        "documents": result.get("documents", []),
    }


@app.post("/api/crawl/run")
def run_manual_crawl(request: CrawlDiscoverRequest):
    with get_db() as conn:
        source = conn.execute(
            """
            SELECT *
            FROM sources
            WHERE id = ?
              AND active = 1
            """,
            (request.source_id,),
        ).fetchone()

    if not source:
        raise HTTPException(
            status_code=404,
            detail="Active source not found.",
        )

    source_data = serialize_source_row(source)
    result = crawl_source(
        source_url=str(source["url"]),
        source_id=int(request.source_id),
        content_types=source_data.get("content_types") or [source_data.get("safety_alert_type")],
        source_name=source_data.get("name"),
        reference_no=source_data.get("reference_no"),
    )

    if result["success"]:
        new_documents, _ = _record_discovered_documents(
            source_data,
            result.get("documents", []),
        )
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO crawl_history
                (source_id, started_at, completed_at, status, documents_found, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    request.source_id,
                    datetime.utcnow().isoformat(),
                    datetime.utcnow().isoformat(),
                    "success",
                    result.get("documents_found", 0),
                    None,
                ),
            )

        return {
            "success": True,
            "source": source_data,
            "documents_found": result.get("documents_found", 0),
            "new_documents": new_documents,
            "documents": result.get("documents", []),
            "message": "Manual crawl completed successfully.",
        }

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO crawl_history
            (source_id, started_at, completed_at, status, documents_found, error_message)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                request.source_id,
                datetime.utcnow().isoformat(),
                datetime.utcnow().isoformat(),
                "failed",
                0,
                result.get("error") or "Manual crawl failed",
            ),
        )

    raise HTTPException(
        status_code=502,
        detail=result.get("error") or "Manual crawl failed.",
    )


selected_processing_jobs = {}


@app.post("/api/crawl/process")
def start_selected_document_processing(
    request: CrawlProcessRequest,
    background_tasks: BackgroundTasks,
):
    with get_db() as conn:
        source = conn.execute(
            """
            SELECT *
            FROM sources
            WHERE id = ?
              AND active = 1
            """,
            (request.source_id,),
        ).fetchone()

    if not source:
        raise HTTPException(
            status_code=404,
            detail="Active source not found.",
        )

    discovered_url = str(request.document_url).strip()

    try:
        parsed = urlparse(discovered_url)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document URL: {exc}",
        )

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=400,
            detail="Document URL must be an HTTP or HTTPS URL.",
        )

    filename = (
        Path(request.filename or "").name
        or Path(urlparse(discovered_url).path).name
    )

    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Selected document must be a PDF.",
        )

    job_id = str(uuid.uuid4())
    selected_processing_jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "progress": 0,
        "stage": "Queued",
        "message": "Selected document processing queued.",
        "selected_document": {
            "title": request.title or filename,
            "meeting_date": request.meeting_date,
            "url": discovered_url,
            "filename": filename,
        },
        "pages_extracted": 0,
        "findings_detected": 0,
        "new_information_detected": 0,
        "topics_extracted": 0,
        "processing_status": None,
        "document_id": None,
        "error": None,
    }

    background_tasks.add_task(
        process_selected_document,
        job_id,
        request.source_id,
        discovered_url,
        request.title,
        filename,
        request.meeting_date,
        request.publication_date,
    )

    return {
        "job_id": job_id,
        "status": "queued",
        "message": "Selected document processing started.",
    }


@app.get("/api/crawl/process/status/{job_id}")
def selected_document_processing_status(job_id: str):
    job = selected_processing_jobs.get(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Selected document processing job not found.",
        )

    return job


def process_selected_document(
    job_id: str,
    source_id: int,
    document_url: str,
    title: Optional[str],
    filename: str,
    meeting_date: Optional[str],
    publication_date: Optional[str],
):
    job = selected_processing_jobs[job_id]
    crawl_started = datetime.utcnow().isoformat()
    document_id = None
    extraction_started = None

    def update(**values):
        job.update(values)

    try:
        update(
            status="running",
            progress=5,
            stage="Validating selection",
            message="Validating the selected document.",
        )

        with get_db() as conn:
            existing = conn.execute(
                """
                SELECT *
                FROM documents
                WHERE url = ?
                """,
                (document_url,),
            ).fetchone()

            if existing and str(existing["status"]).upper() in {
                "PROCESSED",
                "EXTRACTED",
            }:
                page_count = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM document_pages
                    WHERE document_id = ?
                    """,
                    (existing["id"],),
                ).fetchone()[0]
                findings = conn.execute(
                    """
                    SELECT comparison_status
                    FROM findings
                    WHERE document_id = ?
                    """,
                    (existing["id"],),
                ).fetchall()
                existing_pages = conn.execute(
                    """
                    SELECT page_number, page_text
                    FROM document_pages
                    WHERE document_id = ?
                    ORDER BY page_number
                    """,
                    (existing["id"],),
                ).fetchall()
                existing_extraction = conn.execute(
                    """
                    SELECT completed_at
                    FROM extraction_history
                    WHERE document_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (existing["id"],),
                ).fetchone()
                existing_crawl = conn.execute(
                    """
                    SELECT completed_at
                    FROM crawl_history
                    WHERE source_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (source_id,),
                ).fetchone()
                                # If this document was processed before the extraction-history
                # feature was available, create a reusable processing-history
                # record now. This does not re-run extraction or create duplicate
                # findings; it records that the existing extracted pages were
                # successfully reused for this processing request.
                if not existing_extraction:
                    reuse_started = datetime.utcnow().isoformat()
                    reuse_completed = datetime.utcnow().isoformat()

                    conn.execute(
                        """
                        INSERT INTO extraction_history
                        (
                            document_id,
                            started_at,
                            completed_at,
                            status,
                            pages_extracted,
                            error_message
                        )
                        VALUES (?, ?, ?, 'success', ?, NULL)
                        """,
                        (
                            existing["id"],
                            reuse_started,
                            reuse_completed,
                            page_count,
                        ),
                    )

                    existing_extraction = conn.execute(
                        """
                        SELECT completed_at
                        FROM extraction_history
                        WHERE document_id = ?
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (existing["id"],),
                    ).fetchone()
                new_count = sum(
                    1
                    for finding in findings
                    if str(finding["comparison_status"] or "").upper()
                    in {"NEW", "NEW_INFORMATION"}
                )

                document_id = existing["id"]
                update(
                    status="completed",
                    progress=100,
                    stage="Completed",
                    message="Existing extracted document reused successfully.",
                    selected_document={
                        "id": document_id,
                        "title": existing["title"],
                        "meeting_date": existing["meeting_date"],
                        "url": existing["url"],
                        "filename": existing["filename"],
                    },
                    pages_extracted=page_count,
                    findings_detected=len(findings),
                    new_information_detected=new_count,
                    processing_status="PROCESSED",
                    document_id=document_id,
                    topics_extracted=len(
                        extract_meeting_topics(
                            [dict(page) for page in existing_pages]
                        )
                    ),
                    last_crawled=(
                        existing_crawl["completed_at"]
                        if existing_crawl
                        else None
                    ),
                    last_processed=(
                        existing_extraction["completed_at"]
                        if existing_extraction
                        else None
                    ),
                    summary_status="AVAILABLE",
                )
                create_document_summary_pdf(document_id)
                return

            if existing:
                document_id = existing["id"]
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO documents
                    (
                        source_id,
                        title,
                        url,
                        meeting_date,
                        publication_date,
                        filename,
                        discovered_date,
                        status,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'NEW', ?)
                    """,
                    (
                        source_id,
                        title or filename,
                        document_url,
                        meeting_date,
                        publication_date,
                        filename,
                        datetime.utcnow().isoformat(),
                        datetime.utcnow().isoformat(),
                    ),
                )
                document_id = cursor.lastrowid

        create_document_summary_pdf(document_id)

        update(
            progress=15,
            stage="Downloading PDF",
            message=f"Downloading {filename}.",
            document_id=document_id,
        )

        pdf_path = PDF_DIR / filename
        downloaded_path = download_pdf(
            document_url,
            str(pdf_path),
        )

        if not downloaded_path:
            raise RuntimeError("PDF download failed.")

        update(
            progress=35,
            stage="Extracting pages",
            message="Extracting text from the selected PDF.",
        )
        extraction_started = datetime.utcnow().isoformat()
        processed = process_pdf_safe(downloaded_path)

        if not processed.get("success"):
            raise RuntimeError(
                processed.get("error")
                or "PDF text extraction failed."
            )

        pages = processed.get("pages", [])
        sha256 = processed.get("sha256")

        with get_db() as conn:
            for page in pages:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO document_pages
                    (document_id, page_number, page_text)
                    VALUES (?, ?, ?)
                    """,
                    (
                        document_id,
                        page["page_number"],
                        page.get("text", ""),
                    ),
                )

            conn.execute(
                """
                UPDATE documents
                SET filename = ?, sha256 = ?, status = 'EXTRACTED'
                WHERE id = ?
                """,
                (filename, sha256, document_id),
            )

            conn.execute(
                """
                INSERT INTO extraction_history
                (
                    document_id,
                    started_at,
                    completed_at,
                    status,
                    pages_extracted,
                    error_message
                )
                VALUES (?, ?, ?, 'success', ?, NULL)
                """,
                (
                    document_id,
                    extraction_started,
                    datetime.utcnow().isoformat(),
                    len(pages),
                ),
            )

        update(
            progress=65,
            stage="Detecting safety findings",
            message="Applying configured safety triggers.",
            pages_extracted=len(pages),
        )
        findings = remove_duplicate_findings(
            detect_document(pages, load_trigger_config())
        )
        topics = extract_meeting_topics(pages)

        with get_db() as conn:
            historical_rows = conn.execute(
                """
                SELECT
                    product_name,
                    active_substance,
                    safety_topic,
                    trigger_name,
                    evidence
                FROM findings
                WHERE document_id != ?
                """,
                (document_id,),
            ).fetchall()
            historical_findings = [dict(row) for row in historical_rows]

        update(
            progress=80,
            stage="Comparing historical findings",
            message="Checking findings for new information.",
        )

        compared_findings = [
            compare_finding(finding, historical_findings)
            for finding in findings
        ]
        new_count = sum(
            1
            for finding in compared_findings
            if finding.get("comparison_status") == "NEW_INFORMATION"
        )

        with get_db() as conn:
            for finding in compared_findings:
                conn.execute(
                    """
                    INSERT INTO findings
                    (
                        document_id,
                        page_number,
                        product_name,
                        active_substance,
                        safety_topic,
                        trigger_name,
                        evidence,
                        comparison_status,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        finding.get("page_number"),
                        finding.get("product_name"),
                        finding.get("active_substance"),
                        finding.get("safety_topic"),
                        finding.get("trigger_name"),
                        finding.get("evidence"),
                        finding.get(
                            "comparison_status",
                            "NEW_INFORMATION",
                        ),
                        datetime.utcnow().isoformat(),
                    ),
                )

            conn.execute(
                """
                UPDATE documents
                SET status = 'PROCESSED'
                WHERE id = ?
                """,
                (document_id,),
            )
            conn.execute(
                """
                INSERT INTO crawl_history
                (
                    source_id,
                    started_at,
                    completed_at,
                    status,
                    documents_found,
                    error_message
                )
                VALUES (?, ?, ?, 'success', 1, NULL)
                """,
                (
                    source_id,
                    crawl_started,
                    datetime.utcnow().isoformat(),
                ),
            )

        update(
            status="completed",
            progress=100,
            stage="Completed",
            message="Selected document processed successfully.",
            selected_document={
                "id": document_id,
                "title": title or filename,
                "meeting_date": meeting_date,
                "url": document_url,
                "filename": filename,
            },
            findings_detected=len(compared_findings),
            new_information_detected=new_count,
            topics_extracted=len(topics),
            processing_status="PROCESSED",
            document_id=document_id,
        )

        with get_db() as conn:
            extraction = conn.execute(
                """
                SELECT started_at, completed_at
                FROM extraction_history
                WHERE document_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (document_id,),
            ).fetchone()
            crawl = conn.execute(
                """
                SELECT started_at, completed_at, status, documents_found
                FROM crawl_history
                WHERE source_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (source_id,),
            ).fetchone()
        job.update(
            last_crawled=crawl["completed_at"] if crawl else None,
            last_processed=(
                extraction["completed_at"]
                if extraction
                else None
            ),
            summary_status="AVAILABLE",
        )

    except Exception as exc:
        logger.exception(
            "Selected document processing failed for job %s",
            job_id,
        )

        if document_id:
            with get_db() as conn:
                if extraction_started:
                    conn.execute(
                        """
                        INSERT INTO extraction_history
                        (
                            document_id,
                            started_at,
                            completed_at,
                            status,
                            pages_extracted,
                            error_message
                        )
                        VALUES (?, ?, ?, 'failed', 0, ?)
                        """,
                        (
                            document_id,
                            extraction_started,
                            datetime.utcnow().isoformat(),
                            str(exc),
                        ),
                    )
                conn.execute(
                    """
                    UPDATE documents
                    SET status = 'FAILED'
                    WHERE id = ?
                    """,
                    (document_id,),
                )

        update(
            status="failed",
            progress=100,
            stage="Failed",
            message="Selected document processing failed.",
            error=str(exc),
            processing_status="FAILED",
            document_id=document_id,
        )


# ---------------------------------------------------------
# Triggers
# ---------------------------------------------------------

@app.get("/api/triggers")
def get_triggers():
    return [load_trigger_config()]


@app.get("/api/triggers/default")
def get_default_trigger():
    return load_trigger_config()


# ---------------------------------------------------------
# Documents
# ---------------------------------------------------------

@app.get("/api/results")
def list_results(
    source_id: Optional[int] = Query(None, ge=1),
    content_type: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(1000, ge=1, le=5000),
):
    conditions = []
    parameters = []

    if source_id is not None:
        conditions.append("d.source_id = ?")
        parameters.append(source_id)

    if content_type:
        conditions.append("d.content_type = ?")
        parameters.append(content_type)

    if search and search.strip():
        query = f"%{search.strip()}%"
        conditions.append(
            "(d.title LIKE ? OR d.reference_id LIKE ? OR d.url LIKE ?)"
        )
        parameters.extend((query, query, query))

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with get_db() as conn:
        missing_content_types = conn.execute(
            """
            SELECT id, title, url
            FROM documents
            WHERE content_type IS NULL OR content_type = ''
            """
        ).fetchall()
        for document in missing_content_types:
            content_type_value = classify_content_type(
                str(document["title"] or ""),
                str(document["url"] or ""),
            )
            if content_type_value:
                conn.execute(
                    "UPDATE documents SET content_type = ? WHERE id = ?",
                    (content_type_value, document["id"]),
                )

        rows = conn.execute(
            f"""
            SELECT
                d.*,
                s.name AS source_name,
                s.url AS source_url,
                s.reference_no AS source_reference_no,
                (
                    SELECT COUNT(*)
                    FROM document_pages p
                    WHERE p.document_id = d.id
                ) AS pages_extracted,
                (
                    SELECT COUNT(*)
                    FROM findings f
                    WHERE f.document_id = d.id
                ) AS findings_count,
                (
                    SELECT GROUP_CONCAT(DISTINCT f.product_name)
                    FROM findings f
                    WHERE f.document_id = d.id
                      AND f.product_name IS NOT NULL
                      AND f.product_name != ''
                ) AS products_found
            FROM documents d
            JOIN sources s ON s.id = d.source_id
            {where_clause}
            LIMIT ?
            """,
            (*parameters, limit),
        ).fetchall()

        results = []
        for row in rows:
            document = dict(row)
            document_path = urlparse(str(document.get("url") or "")).path.lower()
            content_type_value = document.get("content_type")
            if content_type_value in {"Meeting Minutes", "Agendas"} and (
                "/documents/" not in document_path
                or not document_path.endswith(".pdf")
            ):
                continue
            if content_type_value == "Highlights" and (
                "/en/news/meeting-highlights-" not in document_path
            ):
                continue
            if (
                content_type_value == "PRAC recommendation on signals"
                and not document_path.endswith(".pdf")
            ):
                continue

            reference_id = document.get("reference_id")
            if not reference_id:
                reference_id = _document_reference_id(
                    document.get("source_reference_no"),
                    document.get("publication_date"),
                    int(document["id"]),
                )
                conn.execute(
                    "UPDATE documents SET reference_id = ? WHERE id = ?",
                    (reference_id, document["id"]),
                )

            status = str(document.get("status") or "").upper()
            if status in {"PROCESSED", "EXTRACTED"}:
                working_status = "Yes"
            elif status in {"FAILED", "EXTRACTION_FAILED"}:
                working_status = "Error"
            else:
                working_status = "Pending"

            if document.get("findings_count"):
                trigger_status = "Found"
            elif status == "PROCESSED":
                trigger_status = "Not Found"
            else:
                trigger_status = "Not Analysed"

            filename = document.get("filename")
            local_pdf = PDF_DIR / filename if filename else None
            has_local_pdf = bool(
                local_pdf
                and local_pdf.is_file()
            )

            document.update(
                {
                    "reference_id": reference_id,
                    "date_crawled": (
                        document.get("last_crawled_at")
                        or document.get("discovered_date")
                    ),
                    "crawled_status": "Yes",
                    "working_status": working_status,
                    "safety_trigger_status": trigger_status,
                    "products_found": (
                        [
                            product.strip()
                            for product in document["products_found"].split(",")
                            if product.strip()
                        ]
                        if document.get("products_found")
                        else []
                    ),
                    "has_local_pdf": has_local_pdf,
                    "local_path": str(local_pdf) if has_local_pdf else None,
                }
            )
            results.append(document)

    def published_sort_key(document):
        value = document.get("publication_date")
        if not value:
            return (0, datetime.min)

        cleaned = " ".join(str(value).split())
        for date_format in (
            "%Y-%m-%d",
            "%d %B %Y",
            "%d %b %Y",
            "%d-%B-%Y",
            "%d-%b-%Y",
        ):
            try:
                return (1, datetime.strptime(cleaned, date_format))
            except ValueError:
                continue

        return (0, datetime.min)

    results.sort(
        key=lambda document: (
            published_sort_key(document),
            int(document["id"]),
        ),
        reverse=True,
    )
    return results


@app.get("/api/documents")
def list_documents(
    limit: int = Query(100, ge=1, le=1000),
):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                d.*,
                s.authority,
                s.name AS source_name,
                (
                    SELECT COUNT(*)
                    FROM document_pages p
                    WHERE p.document_id = d.id
                ) AS pages_extracted,
                (
                    SELECT COUNT(*)
                    FROM findings f
                    WHERE f.document_id = d.id
                ) AS findings_count,
                (
                    SELECT COUNT(*)
                    FROM findings f
                    WHERE f.document_id = d.id
                      AND UPPER(COALESCE(f.comparison_status, ''))
                          IN ('NEW', 'NEW_INFORMATION')
                ) AS new_information_count,
                (
                    SELECT COUNT(*)
                    FROM reviews r
                    JOIN findings f
                      ON f.id = r.finding_id
                    WHERE f.document_id = d.id
                ) AS review_count,
                (
                    SELECT COUNT(*)
                    FROM summaries s2
                    JOIN findings f2
                      ON f2.id = s2.finding_id
                    WHERE f2.document_id = d.id
                ) AS summary_count,
                (
                    SELECT ch.completed_at
                    FROM crawl_history ch
                    WHERE ch.source_id = d.source_id
                    ORDER BY ch.id DESC
                    LIMIT 1
                ) AS last_crawled,
                (
                    SELECT eh.completed_at
                    FROM extraction_history eh
                    WHERE eh.document_id = d.id
                    ORDER BY eh.id DESC
                    LIMIT 1
                ) AS last_processed
            FROM documents d
            LEFT JOIN sources s
                ON d.source_id = s.id
            ORDER BY d.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    documents = []
    with get_db() as conn:
        for row in rows:
            document = dict(row)
            topic_pages = conn.execute(
                """
                SELECT page_number, page_text
                FROM document_pages
                WHERE document_id = ?
                ORDER BY page_number
                """,
                (document["id"],),
            ).fetchall()
            document["topics_count"] = len(
                extract_meeting_topics(
                    [dict(page) for page in topic_pages]
                )
            )
            documents.append(document)

    return documents


@app.get("/api/documents/{document_id}")
def get_document(document_id: int):
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT
                d.*,
                s.authority,
                s.name AS source_name,
                (
                    SELECT COUNT(*)
                    FROM document_pages p
                    WHERE p.document_id = d.id
                ) AS pages_extracted,
                (
                    SELECT COUNT(*)
                    FROM findings f
                    WHERE f.document_id = d.id
                ) AS findings_count,
                (
                    SELECT COUNT(*)
                    FROM findings f
                    WHERE f.document_id = d.id
                      AND UPPER(COALESCE(f.comparison_status, ''))
                          IN ('NEW', 'NEW_INFORMATION')
                ) AS new_information_count,
                (
                    SELECT COUNT(*)
                    FROM reviews r
                    JOIN findings f
                      ON f.id = r.finding_id
                    WHERE f.document_id = d.id
                ) AS review_count,
                (
                    SELECT COUNT(*)
                    FROM summaries s2
                    JOIN findings f2
                      ON f2.id = s2.finding_id
                    WHERE f2.document_id = d.id
                ) AS summary_count,
                (
                    SELECT ch.completed_at
                    FROM crawl_history ch
                    WHERE ch.source_id = d.source_id
                    ORDER BY ch.id DESC
                    LIMIT 1
                ) AS last_crawled,
                (
                    SELECT eh.completed_at
                    FROM extraction_history eh
                    WHERE eh.document_id = d.id
                    ORDER BY eh.id DESC
                    LIMIT 1
                ) AS last_processed
            FROM documents d
            LEFT JOIN sources s
                ON d.source_id = s.id
            WHERE d.id = ?
            """,
            (document_id,),
        ).fetchone()
        topic_pages = conn.execute(
            """
            SELECT page_number, page_text
            FROM document_pages
            WHERE document_id = ?
            ORDER BY page_number
            """,
            (document_id,),
        ).fetchall()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    document = dict(row)
    document["topics_count"] = len(
        extract_meeting_topics(
            [dict(page) for page in topic_pages]
        )
    )
    return document


@app.get("/api/documents/{document_id}/pages")
def get_document_pages(document_id: int):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM document_pages
            WHERE document_id = ?
            ORDER BY page_number
            """,
            (document_id,),
        ).fetchall()

    return [dict(row) for row in rows]


@app.get("/api/documents/{document_id}/topics")
def get_document_topics(document_id: int):
    with get_db() as conn:
        document = conn.execute(
            """
            SELECT id, title, meeting_date
            FROM documents
            WHERE id = ?
            """,
            (document_id,),
        ).fetchone()

        if not document:
            raise HTTPException(
                status_code=404,
                detail="Document not found.",
            )

        pages = conn.execute(
            """
            SELECT page_number, page_text
            FROM document_pages
            WHERE document_id = ?
            ORDER BY page_number
            """,
            (document_id,),
        ).fetchall()

    topics = extract_meeting_topics(
        [dict(page) for page in pages]
    )

    return {
        "document_id": document_id,
        "document_title": document["title"],
        "meeting_date": document["meeting_date"],
        "topics": topics,
        "message": (
            None
            if topics
            else "No meeting topics could be extracted from this document."
        ),
    }


@app.get("/api/documents/{document_id}/summary")
def get_document_summary(document_id: int):
    with get_db() as conn:
        document = conn.execute(
            """
            SELECT d.*, s.authority, s.name AS source_name,
                   s.source_type, s.url AS source_url, s.active
            FROM documents d
            LEFT JOIN sources s ON s.id = d.source_id
            WHERE d.id = ?
            """,
            (document_id,),
        ).fetchone()
        if not document:
            raise HTTPException(status_code=404, detail="Document not found.")

        pages = conn.execute(
            """
            SELECT page_number, page_text
            FROM document_pages
            WHERE document_id = ?
            ORDER BY page_number
            """,
            (document_id,),
        ).fetchall()
        findings = conn.execute(
            """
            SELECT f.*, EXISTS(
                SELECT 1 FROM reviews r WHERE r.finding_id = f.id
            ) AS reviewed
            FROM findings f
            WHERE f.document_id = ?
            ORDER BY f.page_number, f.id
            """,
            (document_id,),
        ).fetchall()
        extraction = conn.execute(
            """
            SELECT started_at, completed_at, status, pages_extracted
            FROM extraction_history
            WHERE document_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (document_id,),
        ).fetchone()
        crawl = conn.execute(
            """
            SELECT ch.started_at, ch.completed_at, ch.status,
                   ch.documents_found
            FROM crawl_history ch
            WHERE ch.source_id = ?
            ORDER BY ch.id DESC LIMIT 1
            """,
            (document["source_id"],),
        ).fetchone()

    topics = extract_meeting_topics([dict(page) for page in pages])
    section_summaries = extract_section_summaries(
        [dict(page) for page in pages],
        topics,
    )
    finding_items = [dict(row) for row in findings]
    new_information = [
        finding for finding in finding_items
        if str(finding.get("comparison_status") or "").upper()
        in {"NEW", "NEW_INFORMATION"}
    ]
    try:
        ollama = test_ollama_connection()
    except Exception as exc:
        ollama = {
            "available": False,
            "model_available": False,
            "message": str(exc),
        }

    return {
        "document": dict(document),
        "topics": topics,
        "section_summaries": section_summaries,
        "executive_summary": (
            "The meeting minutes cover "
            + ", ".join(
                str(section["title"])
                for section in section_summaries[:8]
            )
            + "."
            if section_summaries
            else "Source text was insufficient to generate a detailed deterministic summary."
        ),
        "findings": finding_items,
        "new_information": new_information,
        "pages_extracted": len(pages),
        "topics_count": len(topics),
        "findings_count": len(finding_items),
        "new_information_count": len(new_information),
        "crawl": dict(crawl) if crawl else None,
        "processing": dict(extraction) if extraction else None,
        "configuration": {
            "section_xpath": PRAC_SECTION_XPATH,
            "meeting_pdf_xpath": PRAC_MEETING_XPATH,
            "trigger": load_trigger_config(),
        },
        "ai_status": ollama,
        "summary_status": "AVAILABLE",
        "summary_note": (
            "Topics were extracted deterministically from numbered "
            "headings in the source Meeting Minutes PDF. This is not "
            "an AI-generated regulatory conclusion."
        ),
    }


@app.get("/api/documents/{document_id}/metadata")
def document_metadata(document_id: int):
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT filename
            FROM documents
            WHERE id = ?
            """,
            (document_id,),
        ).fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    filename = row["filename"]

    if not filename:
        raise HTTPException(
            status_code=404,
            detail="PDF filename is not available.",
        )

    pdf_path = PDF_DIR / filename

    if not pdf_path.exists():
        raise HTTPException(
            status_code=404,
            detail="PDF file not found.",
        )

    return get_pdf_metadata(pdf_path)


@app.get("/api/documents/{document_id}/pdf")
def download_document_pdf(document_id: int):
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT filename, title
            FROM documents
            WHERE id = ?
            """,
            (document_id,),
        ).fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    filename = row["filename"]

    if not filename:
        raise HTTPException(
            status_code=404,
            detail="PDF filename not available.",
        )

    pdf_path = PDF_DIR / filename

    if not pdf_path.exists():
        raise HTTPException(
            status_code=404,
            detail="PDF file not found.",
        )

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=filename,
    )


# ---------------------------------------------------------
# Pages
# ---------------------------------------------------------

@app.get("/api/pages/{document_id}/{page_number}")
def get_page(
    document_id: int,
    page_number: int,
):
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM document_pages
            WHERE document_id = ?
              AND page_number = ?
            """,
            (
                document_id,
                page_number,
            ),
        ).fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Page not found.",
        )

    return dict(row)


# ---------------------------------------------------------
# Findings
# ---------------------------------------------------------

@app.get("/api/findings")
def list_findings(
    limit: int = Query(100, ge=1, le=1000),
    document_id: Optional[int] = Query(None, ge=1),
    trigger_name: Optional[str] = Query(None),
    comparison_status: Optional[str] = Query(None),
    review_status: Optional[str] = Query(None),
):
    with get_db() as conn:
        query = """
            SELECT
                f.*,
                d.title AS document_title,
                d.filename,
                d.url AS document_url
            FROM findings f
            LEFT JOIN documents d
                ON f.document_id = d.id
        """
        parameters = []
        conditions = []
        if document_id is not None:
            conditions.append("f.document_id = ?")
            parameters.append(document_id)
        if trigger_name:
            conditions.append("LOWER(COALESCE(f.trigger_name, '')) = LOWER(?)")
            parameters.append(trigger_name)
        if comparison_status:
            if comparison_status.upper() == "NEW_INFORMATION":
                conditions.append(
                    "UPPER(COALESCE(f.comparison_status, '')) IN ('NEW', 'NEW_INFORMATION')"
                )
            else:
                conditions.append(
                    "UPPER(COALESCE(f.comparison_status, '')) = UPPER(?)"
                )
                parameters.append(comparison_status)
        if review_status:
            if review_status.upper() == "REVIEWED":
                conditions.append(
                    "EXISTS (SELECT 1 FROM reviews rr WHERE rr.finding_id = f.id)"
                )
            elif review_status.upper() == "PENDING":
                conditions.append(
                    "NOT EXISTS (SELECT 1 FROM reviews rr WHERE rr.finding_id = f.id)"
                )
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY f.created_at DESC LIMIT ?"
        parameters.append(limit)
        rows = conn.execute(query, parameters).fetchall()

    findings = []
    with get_db() as conn:
        for row in rows:
            finding = dict(row)
            for field in (
                "relevant_terms",
                "section",
                "evidence_hash",
            ):
                finding.setdefault(field, None)
            summary = conn.execute(
                """
                SELECT *
                FROM summaries
                WHERE finding_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (finding["id"],),
            ).fetchone()
            finding["summary"] = dict(summary) if summary else None
            review = conn.execute(
                """
                SELECT id, reviewer, decision, comments, reviewed_at
                FROM reviews
                WHERE finding_id = ?
                ORDER BY reviewed_at DESC, id DESC
                LIMIT 1
                """,
                (finding["id"],),
            ).fetchone()
            finding["latest_review"] = dict(review) if review else None
            finding["review_status"] = "REVIEWED" if review else "PENDING"
            if finding["summary"]:
                finding["summary"]["model"] = os.getenv(
                    "OLLAMA_MODEL",
                    "llama3.2",
                )
                finding["summary"]["status"] = "GENERATED"
            findings.append(finding)

    return findings


@app.get("/api/findings/new")
def list_new_information(
    limit: int = Query(100, ge=1, le=1000),
):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                f.*,
                d.title AS document_title,
                d.filename,
                d.url AS document_url
            FROM findings f
            LEFT JOIN documents d
                ON f.document_id = d.id
            WHERE UPPER(COALESCE(f.comparison_status, ''))
                IN ('NEW', 'NEW_INFORMATION')
            ORDER BY f.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        findings = []
        for row in rows:
            finding = dict(row)
            for field in (
                "relevant_terms",
                "section",
                "evidence_hash",
            ):
                finding.setdefault(field, None)
            summary = conn.execute(
                """
                SELECT *
                FROM summaries
                WHERE finding_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (finding["id"],),
            ).fetchone()
            finding["summary"] = dict(summary) if summary else None
            review = conn.execute(
                """
                SELECT id, reviewer, decision, comments, reviewed_at
                FROM reviews
                WHERE finding_id = ?
                ORDER BY reviewed_at DESC, id DESC
                LIMIT 1
                """,
                (finding["id"],),
            ).fetchone()
            finding["latest_review"] = dict(review) if review else None
            finding["review_status"] = "REVIEWED" if review else "PENDING"
            if finding["summary"]:
                finding["summary"]["model"] = os.getenv(
                    "OLLAMA_MODEL",
                    "llama3.2",
                )
                finding["summary"]["status"] = "GENERATED"
            findings.append(finding)

    return findings


@app.get("/api/findings/{finding_id}")
def get_finding(finding_id: int):
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT
                f.*,
                d.title AS document_title,
                d.filename,
                d.url AS document_url
            FROM findings f
            LEFT JOIN documents d
                ON f.document_id = d.id
            WHERE f.id = ?
            """,
            (finding_id,),
        ).fetchone()
        summary_row = conn.execute(
            """
            SELECT *
            FROM summaries
            WHERE finding_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (finding_id,),
        ).fetchone()

        page_row = conn.execute(
            """
            SELECT
                p.page_text,
                d.title AS document_title,
                d.url AS document_url,
                d.filename
            FROM findings f
            LEFT JOIN document_pages p
                ON p.document_id = f.document_id
               AND p.page_number = f.page_number
            LEFT JOIN documents d
                ON d.id = f.document_id
            WHERE f.id = ?
            """,
            (finding_id,),
        ).fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Finding not found.",
        )

    result = dict(row)
    for field in (
        "relevant_terms",
        "section",
        "evidence_hash",
    ):
        result.setdefault(field, None)
    result["summary"] = dict(summary_row) if summary_row else None
    if result["summary"]:
        result["summary"]["model"] = os.getenv(
            "OLLAMA_MODEL",
            "llama3.2",
        )
        result["summary"]["status"] = "GENERATED"
    with get_db() as conn:
        review_row = conn.execute(
            """
            SELECT id, reviewer, decision, comments, reviewed_at
            FROM reviews
            WHERE finding_id = ?
            ORDER BY reviewed_at DESC, id DESC
            LIMIT 1
            """,
            (finding_id,),
        ).fetchone()
    result["latest_review"] = dict(review_row) if review_row else None
    result["review_status"] = "REVIEWED" if review_row else "PENDING"

    page_text = page_row["page_text"] if page_row else None
    result["evidence_detail"] = {
        "exact_text": result.get("evidence"),
        "evidence_hash": result.get("evidence_hash"),
        "document_id": result.get("document_id"),
        "page_number": result.get("page_number"),
        "page_text": page_text,
        "document_title": (
            page_row["document_title"]
            if page_row
            else result.get("document_title")
        ),
        "document_url": (
            page_row["document_url"]
            if page_row
            else result.get("document_url")
        ),
        "filename": (
            page_row["filename"]
            if page_row
            else result.get("filename")
        ),
        "warning": (
            None
            if page_text is not None
            else "The exact source page is unavailable."
        ),
    }

    return result


# ---------------------------------------------------------
# Summaries
# ---------------------------------------------------------

@app.get("/api/summaries")
def list_summaries(
    limit: int = Query(100, ge=1, le=1000),
):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM summaries
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    summaries = []
    for row in rows:
        summary = dict(row)
        summary["model"] = os.getenv(
            "OLLAMA_MODEL",
            "llama3.2",
        )
        summary["status"] = "GENERATED"
        summaries.append(summary)

    return summaries


@app.post("/api/summaries/generate/{finding_id}")
def generate_summary(finding_id: int):

    with get_db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM findings
            WHERE id = ?
            """,
            (finding_id,),
        ).fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Finding not found.",
        )

    finding = dict(row)

    evidence = str(finding.get("evidence") or "").strip()
    if not evidence:
        return {
            "success": False,
            "status": "NO_EVIDENCE",
            "message": "The finding has no exact evidence to summarize.",
        }

    try:
        result = generate_summary_from_finding(finding)

    except Exception as exc:
        logger.exception("Ollama summary generation failed")

        return {
            "success": False,
            "status": "ERROR",
            "message": str(exc),
        }

    if not result:
        return {
            "success": False,
            "status": "UNAVAILABLE",
            "message": "Ollama summary was not generated.",
        }

    if not isinstance(result, dict):
        return {
            "success": False,
            "status": "INVALID_RESPONSE",
            "message": "Ollama returned an invalid response.",
        }

    status = result.get("status", "ERROR")
    model = result.get("model") or os.getenv("OLLAMA_MODEL", "llama3.2")
    if status != "SUCCESS":
        return {
            "success": False,
            "status": status,
            "model": model,
            "message": result.get("error") or "Ollama summary was not generated.",
        }

    summary_text = result.get("summary")
    prac_assessment = result.get("prac_assessment")
    outcome = result.get("outcome")

    if not isinstance(summary_text, str) or not summary_text.strip():
        return {
            "success": False,
            "status": "INVALID_RESPONSE",
            "model": model,
            "message": "Ollama returned no usable summary.",
        }

    if not all(
        value is None or isinstance(value, str)
        for value in (
            result.get("product_name"),
            result.get("active_substance"),
            result.get("safety_topic"),
            prac_assessment,
            outcome,
            summary_text,
        )
    ):
        return {
            "success": False,
            "status": "INVALID_RESPONSE",
            "model": model,
            "message": "Ollama returned fields with invalid types.",
        }

    now = datetime.utcnow().isoformat()

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO summaries
            (
                finding_id,
                product_name,
                active_substance,
                safety_topic,
                prac_assessment,
                outcome,
                summary,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                finding_id,
                result.get("product_name") or finding.get("product_name"),
                result.get("active_substance") or finding.get("active_substance"),
                result.get("safety_topic") or finding.get("safety_topic"),
                prac_assessment,
                outcome,
                summary_text.strip(),
                now,
            ),
        )

    return {
        "success": True,
        "status": "GENERATED",
        "summary": summary_text.strip(),
        "model": model,
        "created_at": now,
        "prac_assessment": prac_assessment,
        "outcome": outcome,
    }


# ---------------------------------------------------------
# Ollama
# ---------------------------------------------------------

@app.get("/api/ollama/test")
def ollama_test():
    try:
        return test_ollama_connection()

    except Exception as exc:
        logger.exception("Ollama connection test failed")

        return {
            "available": False,
            "model_available": False,
            "message": str(exc),
            "error": str(exc),
        }


# ---------------------------------------------------------
# Reviews
# ---------------------------------------------------------

@app.post("/api/reviews")
def create_review(review: ReviewCreate):

    now = datetime.utcnow().isoformat()

    with get_db() as conn:

        finding = conn.execute(
            """
            SELECT id
            FROM findings
            WHERE id = ?
            """,
            (review.finding_id,),
        ).fetchone()

        if not finding:
            raise HTTPException(
                status_code=404,
                detail="Finding not found.",
            )

        cursor = conn.execute(
            """
            INSERT INTO reviews
            (
                finding_id,
                reviewer,
                decision,
                comments,
                reviewed_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                review.finding_id,
                review.reviewer,
                review.decision,
                review.comments,
                now,
            ),
        )

        review_id = cursor.lastrowid

    return {
        "success": True,
        "id": review_id,
        "message": "Review recorded successfully.",
    }


@app.get("/api/reviews")
def list_reviews():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                r.*,
                f.product_name,
                f.active_substance,
                f.safety_topic,
                f.page_number,
                d.title AS document_title,
                d.filename
            FROM reviews r
            LEFT JOIN findings f
                ON r.finding_id = f.id
            LEFT JOIN documents d
                ON f.document_id = d.id
            ORDER BY r.reviewed_at DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


@app.put("/api/reviews/{review_id}")
def update_review(review_id: int, review: ReviewUpdate):
    now = datetime.utcnow().isoformat()

    with get_db() as conn:
        cursor = conn.execute(
            """
            UPDATE reviews
            SET reviewer = ?, decision = ?, comments = ?, reviewed_at = ?
            WHERE id = ?
            """,
            (
                review.reviewer,
                review.decision,
                review.comments,
                now,
                review_id,
            ),
        )

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Review not found.",
            )

    return {
        "success": True,
        "message": "Review updated successfully.",
    }


@app.delete("/api/reviews/{review_id}")
def delete_review(review_id: int):
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM reviews WHERE id = ?",
            (review_id,),
        )

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Review not found.",
            )

    return {
        "success": True,
        "message": "Review deleted successfully.",
    }

def create_document_summary_pdf(document_id: int) -> Path:
    """
    Create a traceable review-support PDF for a PRAC document.

    The report uses only information already stored by the POC.
    It includes document dates, extracted page count, findings,
    evidence, comparison status, available Ollama summaries,
    crawler XPath configuration, and reviewer decisions.
    """

    with get_db() as conn:

        document = conn.execute(
            """
            SELECT
                d.*,
                s.authority,
                s.name AS source_name,
                s.source_type,
                s.active AS source_active,
                s.url AS source_url
            FROM documents d
            LEFT JOIN sources s
                ON d.source_id = s.id
            WHERE d.id = ?
            """,
            (document_id,),
        ).fetchone()

        if not document:
            raise ValueError("Document not found.")

        findings = conn.execute(
            """
            SELECT *
            FROM findings
            WHERE document_id = ?
            ORDER BY page_number, id
            """,
            (document_id,),
        ).fetchall()

        summaries = conn.execute(
            """
            SELECT
                s.*,
                f.page_number,
                f.evidence,
                f.comparison_status
            FROM summaries s
            LEFT JOIN findings f
                ON s.finding_id = f.id
            WHERE f.document_id = ?
            ORDER BY f.page_number, s.id
            """,
            (document_id,),
        ).fetchall()

        reviews = conn.execute(
            """
            SELECT
                r.*,
                f.page_number,
                f.product_name,
                f.active_substance,
                f.safety_topic
            FROM reviews r
            LEFT JOIN findings f
                ON r.finding_id = f.id
            WHERE f.document_id = ?
            ORDER BY r.reviewed_at DESC
            """,
            (document_id,),
        ).fetchall()

        page_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM document_pages
            WHERE document_id = ?
            """,
            (document_id,),
        ).fetchone()["count"]

        new_information_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM findings
            WHERE document_id = ?
              AND UPPER(COALESCE(comparison_status, ''))
                  IN ('NEW', 'NEW_INFORMATION')
            """,
            (document_id,),
        ).fetchone()["count"]

        topic_pages = conn.execute(
            """
            SELECT page_number, page_text
            FROM document_pages
            WHERE document_id = ?
            ORDER BY page_number
            """,
            (document_id,),
        ).fetchall()
        topics = extract_meeting_topics(
            [dict(page) for page in topic_pages]
        )
        section_summaries = extract_section_summaries(
            [dict(page) for page in topic_pages],
            topics,
        )
        extraction = conn.execute(
            """
            SELECT started_at, completed_at, status, pages_extracted
            FROM extraction_history
            WHERE document_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (document_id,),
        ).fetchone()
        crawl = conn.execute(
            """
            SELECT started_at, completed_at, status, documents_found
            FROM crawl_history
            WHERE source_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (document["source_id"],),
        ).fetchone()

    title = (
        document["title"]
        or document["filename"]
        or "PRAC Meeting Minutes"
    )

    safe_title = re.sub(
        r"[^A-Za-z0-9_-]+",
        "_",
        title,
    ).strip("_")

    if not safe_title:
        safe_title = "PRAC_Meeting_Minutes"

    output_path = (
        SUMMARY_DIR
        / f"summary_{document_id}_{safe_title}.pdf"
    )

    styles = getSampleStyleSheet()

    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            spaceAfter=12,
            textColor=colors.HexColor("#10213f"),
        )
    )

    styles.add(
        ParagraphStyle(
            name="SectionTitle",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            spaceBefore=12,
            spaceAfter=8,
            textColor=colors.HexColor("#10213f"),
        )
    )

    styles.add(
        ParagraphStyle(
            name="BodySmall",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=12,
            spaceAfter=5,
        )
    )

    styles.add(
        ParagraphStyle(
            name="BodySmallBold",
            parent=styles["BodySmall"],
            fontName="Helvetica-Bold",
        )
    )

    styles.add(
        ParagraphStyle(
            name="Evidence",
            parent=styles["BodySmall"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            leftIndent=8,
            spaceAfter=5,
        )
    )

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Safety Review Summary - {title}",
        author="Safety Trigger Monitoring POC",
    )

    story = []

    story.append(
        Paragraph(
            "SAFETY TRIGGER MONITORING",
            styles["BodySmallBold"],
        )
    )

    story.append(
        Paragraph(
            "PRAC Meeting Minutes Safety Review Summary",
            styles["ReportTitle"],
        )
    )

    story.append(
        Paragraph(
            "MEETING MINUTES SUMMARY",
            styles["SectionTitle"],
        )
    )

    metadata = [
        ["Document", str(title)],
        [
            "Health authority",
            str(
                document["authority"]
                or "European Medicines Agency"
            ),
        ],
        [
            "Source",
            str(
                document["source_name"]
                or "EMA PRAC"
            ),
        ],
        [
            "Meeting date",
            str(
                document["meeting_date"]
                or "Not extracted"
            ),
        ],
        [
            "Publication date",
            str(
                document["publication_date"]
                or "Not available"
            ),
        ],
        [
            "PDF filename",
            str(
                document["filename"]
                or "Not available"
            ),
        ],
        [
            "Pages extracted",
            str(page_count),
        ],
        [
            "Safety findings",
            str(len(findings)),
        ],
        [
            "NEW INFORMATION",
            str(new_information_count),
        ],
    ]

    metadata_table = Table(
        metadata,
        colWidths=[42 * mm, 130 * mm],
        repeatRows=0,
    )

    metadata_table.setStyle(
        TableStyle(
            [
                (
                    "FONTNAME",
                    (0, 0),
                    (0, -1),
                    "Helvetica-Bold",
                ),
                (
                    "FONTNAME",
                    (1, 0),
                    (1, -1),
                    "Helvetica",
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "LEADING",
                    (0, 0),
                    (-1, -1),
                    11,
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.HexColor("#eef3f9"),
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.25,
                    colors.HexColor("#d4dce8"),
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    5,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    5,
                ),
            ]
        )
    )

    story.append(metadata_table)
    story.append(Spacer(1, 8))

    history_data = [
        ["Crawl started", str(crawl["started_at"] if crawl else "Not available")],
        ["Crawl completed", str(crawl["completed_at"] if crawl else "Not available")],
        ["Processing started", str(extraction["started_at"] if extraction else "Not available")],
        ["Processing completed", str(extraction["completed_at"] if extraction else "Not available")],
        ["Crawl status", str(crawl["status"] if crawl else "Not available")],
        ["Processing status", str(extraction["status"] if extraction else "Not available")],
        ["Topics extracted", str(len(topics))],
        ["AI status", "Unavailable — deterministic summary; configured Ollama model is not installed."],
    ]
    history_table = Table(history_data, colWidths=[42 * mm, 130 * mm])
    history_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3f9")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d4dce8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(history_table)
    story.append(Spacer(1, 8))

    story.append(Paragraph("EXECUTIVE SUMMARY", styles["SectionTitle"]))
    story.append(Paragraph(
        (
            "The meeting minutes cover "
            + html_escape(", ".join(str(section["title"]) for section in section_summaries[:8]))
            + "."
            if section_summaries
            else "Source text was insufficient to generate a detailed deterministic summary."
        ),
        styles["BodySmall"],
    ))
    story.append(Paragraph("KEY MEETING TOPICS", styles["SectionTitle"]))
    for section in section_summaries:
        story.append(Paragraph(
            f"{html_escape(str(section.get('section_number') or ''))} "
            f"{html_escape(str(section.get('title') or ''))}",
            styles["BodySmallBold"],
        ))
        story.append(Paragraph(
            html_escape(str(section.get("summary") or "")),
            styles["BodySmall"],
        ))
        story.append(Paragraph(
            f"Source pages: {section.get('source_page_start')}–"
            f"{section.get('source_page_end')}",
            styles["BodySmall"],
        ))

    story.append(Paragraph("DETAILED MEETING TOPICS", styles["SectionTitle"]))
    story.append(Paragraph(
        "Topics were extracted deterministically from numbered headings in the source Meeting Minutes PDF. "
        "This is not an AI-generated regulatory conclusion.",
        styles["BodySmall"],
    ))
    if topics:
        for topic in topics:
            title_text = html_escape(str(topic.get("title") or "Untitled topic"))
            page_text = html_escape(str(topic.get("page_number") or "—"))
            source_text = topic.get("source_text")
            detail = (
                f"<br/><i>{html_escape(str(source_text))}</i>"
                if source_text and source_text != topic.get("title")
                else ""
            )
            story.append(Paragraph(
                f"{html_escape(str(topic.get('section_number') or ''))} "
                f"{title_text} — Source page: {page_text}{detail}",
                styles["BodySmall"],
            ))
    else:
        story.append(Paragraph(
            "No meeting topics could be extracted from this document.",
            styles["BodySmall"],
        ))

    story.append(
        Paragraph(
            "Source URL",
            styles["SectionTitle"],
        )
    )

    story.append(
        Paragraph(
            str(document["url"]),
            styles["BodySmall"],
        )
    )

    story.append(
        Paragraph(
            "COMPARISON RESULT",
            styles["SectionTitle"],
        )
    )

    if new_information_count > 0:
        result_text = (
            f"NEW INFORMATION detected: "
            f"{new_information_count} finding(s) were classified as NEW "
            f"after comparison with existing findings."
        )
    elif findings:
        result_text = (
            "No NEW INFORMATION was identified by the comparison "
            "step for the detected findings."
        )
    else:
        result_text = (
            "No trigger-relevant safety findings were detected."
        )

    story.append(
        Paragraph(
            result_text,
            styles["BodySmall"],
        )
    )

    story.append(
        Paragraph(
            "DETECTED SAFETY INFORMATION",
            styles["SectionTitle"],
        )
    )

    if not findings:

        story.append(
            Paragraph(
                "No trigger-relevant findings are stored for this document.",
                styles["BodySmall"],
            )
        )

    else:

        for index, finding in enumerate(
            findings,
            start=1,
        ):

            finding_data = [
                [
                    Paragraph(
                        f"Finding {index}",
                        styles["BodySmallBold"],
                    ),
                    "",
                ],
                [
                    "Product",
                    str(
                        finding["product_name"]
                        or "Not identified"
                    ),
                ],
                [
                    "Active substance",
                    str(
                        finding["active_substance"]
                        or "Not identified"
                    ),
                ],
                [
                    "Safety topic",
                    str(
                        finding["safety_topic"]
                        or "Not identified"
                    ),
                ],
                [
                    "Page",
                    str(
                        finding["page_number"]
                        or "—"
                    ),
                ],
                [
                    "Comparison",
                    str(
                        finding["comparison_status"]
                        or "Not compared"
                    ),
                ],
                [
                    "Relevant terms",
                    str(
                        finding["relevant_terms"]
                        or "—"
                    ),
                ],
            ]

            finding_table = Table(
                finding_data,
                colWidths=[42 * mm, 130 * mm],
            )

            finding_table.setStyle(
                TableStyle(
                    [
                        (
                            "SPAN",
                            (0, 0),
                            (1, 0),
                        ),
                        (
                            "FONTNAME",
                            (0, 0),
                            (-1, 0),
                            "Helvetica-Bold",
                        ),
                        (
                            "FONTNAME",
                            (0, 1),
                            (0, -1),
                            "Helvetica-Bold",
                        ),
                        (
                            "FONTSIZE",
                            (0, 0),
                            (-1, -1),
                            8,
                        ),
                        (
                            "VALIGN",
                            (0, 0),
                            (-1, -1),
                            "TOP",
                        ),
                        (
                            "BACKGROUND",
                            (0, 0),
                            (-1, 0),
                            colors.HexColor("#eef3f9"),
                        ),
                        (
                            "GRID",
                            (0, 0),
                            (-1, -1),
                            0.25,
                            colors.HexColor("#d4dce8"),
                        ),
                        (
                            "LEFTPADDING",
                            (0, 0),
                            (-1, -1),
                            6,
                        ),
                        (
                            "RIGHTPADDING",
                            (0, 0),
                            (-1, -1),
                            6,
                        ),
                        (
                            "TOPPADDING",
                            (0, 0),
                            (-1, -1),
                            4,
                        ),
                        (
                            "BOTTOMPADDING",
                            (0, 0),
                            (-1, -1),
                            4,
                        ),
                    ]
                )
            )

            story.append(finding_table)
            story.append(Spacer(1, 5))

            story.append(
                Paragraph(
                    "Exact evidence:",
                    styles["BodySmallBold"],
                )
            )

            evidence = (
                finding["evidence"]
                or "No evidence text available."
            )

            evidence_text = str(evidence).replace(
                "\n",
                "<br/>",
            )

            story.append(
                Paragraph(
                    evidence_text,
                    styles["Evidence"],
                )
            )

    if summaries:

        story.append(
            Paragraph(
                "OLLAMA EVIDENCE SUMMARIES",
                styles["SectionTitle"],
            )
        )

        for index, summary in enumerate(
            summaries,
            start=1,
        ):

            story.append(
                Paragraph(
                    (
                        f"Summary {index} "
                        f"(Page {summary['page_number'] or '—'})"
                    ),
                    styles["BodySmallBold"],
                )
            )

            summary_text = (
                summary["summary"]
                or "No summary text available."
            )

            story.append(
                Paragraph(
                    str(summary_text).replace(
                        "\n",
                        "<br/>",
                    ),
                    styles["BodySmall"],
                )
            )

            story.append(
                Paragraph(
                    (
                        f"Model: "
                        f"{summary['model'] or 'Not available'} | "
                        f"Status: "
                        f"{summary['status'] or '—'}"
                    ),
                    styles["BodySmall"],
                )
            )

    story.append(
        Paragraph(
            "REVIEW HISTORY",
            styles["SectionTitle"],
        )
    )

    if reviews:

        review_data = [
            [
                "Reviewed",
                "Reviewer",
                "Decision",
                "Page",
                "Comments",
            ]
        ]

        for review in reviews:

            review_data.append(
                [
                    str(
                        review["reviewed_at"]
                        or "—"
                    ),
                    str(
                        review["reviewer"]
                        or "—"
                    ),
                    str(
                        review["decision"]
                        or "—"
                    ),
                    str(
                        review["page_number"]
                        or "—"
                    ),
                    str(
                        review["comments"]
                        or "—"
                    ),
                ]
            )

        review_table = Table(
            review_data,
            colWidths=[
                28 * mm,
                28 * mm,
                28 * mm,
                15 * mm,
                71 * mm,
                ],
            repeatRows=1,
        )

        review_table.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        colors.HexColor("#eef3f9"),
                    ),
                    (
                        "FONTNAME",
                        (0, 0),
                        (-1, 0),
                        "Helvetica-Bold",
                    ),
                    (
                        "FONTSIZE",
                        (0, 0),
                        (-1, -1),
                        7,
                    ),
                    (
                        "GRID",
                        (0, 0),
                        (-1, -1),
                        0.25,
                        colors.HexColor("#d4dce8"),
                    ),
                    (
                        "VALIGN",
                        (0, 0),
                        (-1, -1),
                        "TOP",
                    ),
                    (
                        "LEFTPADDING",
                        (0, 0),
                        (-1, -1),
                        4,
                    ),
                    (
                        "RIGHTPADDING",
                        (0, 0),
                        (-1, -1),
                        4,
                    ),
                    (
                        "TOPPADDING",
                        (0, 0),
                        (-1, -1),
                        4,
                    ),
                    (
                        "BOTTOMPADDING",
                        (0, 0),
                        (-1, -1),
                        4,
                    ),
                ]
            )
        )

        story.append(review_table)

    else:

        story.append(
            Paragraph(
                "No human review has been recorded for this document.",
                styles["BodySmall"],
            )
        )

    story.append(
        Paragraph(
            "CONFIGURATION USED",
            styles["SectionTitle"],
        )
    )
    trigger = load_trigger_config()
    configuration_data = [
        ["Health authority", str(document["authority"] or "Not available")],
        ["Source name", str(document["source_name"] or "Not available")],
        ["Source URL", str(document["source_url"] or "Not available")],
        ["Source type", str(document["source_type"] or "Not available")],
        ["Active status", "Active" if document["source_active"] else "Inactive"],
        ["Meeting Minutes XPath", PRAC_SECTION_XPATH],
        ["Meeting PDF XPath", PRAC_MEETING_XPATH],
        ["Safety trigger", str(trigger.get("name") or "Not available")],
        [
            "Safety terms",
            ", ".join(str(term) for term in trigger.get("safety_terms", [])),
        ],
    ]
    configuration_table = Table(
        configuration_data,
        colWidths=[48 * mm, 124 * mm],
    )
    configuration_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3f9")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d4dce8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(configuration_table)
    story.append(Spacer(1, 8))

    story.append(
        Paragraph(
            "TRACEABILITY",
            styles["SectionTitle"],
        )
    )

    trace_data = [
        [
            "PRAC section XPath",
            PRAC_SECTION_XPATH,
        ],
        [
            "Meeting PDF XPath",
            PRAC_MEETING_XPATH,
        ],
        [
            "Document page count",
            str(page_count),
        ],
        [
            "Meeting date extraction",
            (
                "Extracted from the discovered meeting-minute "
                "document title/filename when available."
            ),
        ],
        [
            "Source discovery",
            (
                "The configured source URL is crawled and all "
                "matching PRAC meeting-minute PDF links are discovered."
            ),
        ],
    ]

    trace_table = Table(
        trace_data,
        colWidths=[48 * mm, 124 * mm],
    )

    trace_table.setStyle(
        TableStyle(
            [
                (
                    "FONTNAME",
                    (0, 0),
                    (0, -1),
                    "Helvetica-Bold",
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    7.5,
                ),
                (
                    "LEADING",
                    (0, 0),
                    (-1, -1),
                    10,
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.HexColor("#eef3f9"),
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.25,
                    colors.HexColor("#d4dce8"),
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    5,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    5,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    4,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    4,
                ),
            ]
        )
    )

    story.append(trace_table)
    story.append(Spacer(1, 8))

    story.append(
        Paragraph(
            "This report is a review-support artifact. "
            "It summarizes extracted evidence and comparison results "
            "and does not make a final medical or regulatory decision.",
            styles["BodySmall"],
        )
    )

    doc.build(story)

    return output_path


# ---------------------------------------------------------
# History
# ---------------------------------------------------------
@app.get("/api/history")
def history():
    """
    Return complete audit history.

    This endpoint is intentionally tolerant of older SQLite schemas.
    It does not assume optional summary timestamp columns exist.
    """

    try:
        with get_db() as conn:

            # -------------------------------------------------
            # CRAWL HISTORY
            # -------------------------------------------------
            crawl = conn.execute(
                """
                SELECT
                    ch.*,
                    s.authority,
                    s.name AS source_name,
                    s.url AS source_url
                FROM crawl_history ch
                LEFT JOIN sources s
                    ON ch.source_id = s.id
                ORDER BY ch.id DESC
                LIMIT 100
                """
            ).fetchall()

            # -------------------------------------------------
            # EXTRACTION HISTORY
            # -------------------------------------------------
            extraction = conn.execute(
                """
                SELECT
                    eh.*,
                    d.title AS document_title,
                    d.filename,
                    d.meeting_date,
                    d.publication_date
                FROM extraction_history eh
                LEFT JOIN documents d
                    ON eh.document_id = d.id
                ORDER BY eh.id DESC
                LIMIT 100
                """
            ).fetchall()

            # -------------------------------------------------
            # DETECTION HISTORY
            # -------------------------------------------------
            detection = conn.execute(
                """
                SELECT
                    d.id AS document_id,
                    d.title AS document_title,
                    d.filename,
                    d.meeting_date,
                    d.publication_date,
                    MIN(f.created_at) AS detected_at,
                    MAX(f.created_at) AS last_detected_at,
                    COUNT(f.id) AS findings_count,
                    SUM(
                        CASE
                            WHEN UPPER(
                                COALESCE(
                                    f.comparison_status,
                                    ''
                                )
                            ) IN (
                                'NEW',
                                'NEW_INFORMATION'
                            )
                            THEN 1
                            ELSE 0
                        END
                    ) AS new_information_count
                FROM documents d
                JOIN findings f
                    ON d.id = f.document_id
                GROUP BY
                    d.id,
                    d.title,
                    d.filename,
                    d.meeting_date,
                    d.publication_date,
                    d.created_at
                ORDER BY d.id DESC
                LIMIT 100
                """
            ).fetchall()

            # -------------------------------------------------
            # SUMMARY HISTORY
            # -------------------------------------------------
            #
            # IMPORTANT:
            # Do not reference s.generated_at here because
            # older versions of the SQLite database may not
            # contain that column.
            #
            summary = conn.execute(
                """
                SELECT
                    s.*,
                    f.document_id,
                    f.page_number,
                    d.title AS document_title
                FROM summaries s
                LEFT JOIN findings f
                    ON s.finding_id = f.id
                LEFT JOIN documents d
                    ON f.document_id = d.id
                ORDER BY s.id DESC
                LIMIT 100
                """
            ).fetchall()

            # -------------------------------------------------
            # REVIEW HISTORY
            # -------------------------------------------------
            reviews = conn.execute(
                """
                SELECT
                    r.*,
                    f.product_name,
                    f.active_substance,
                    f.safety_topic,
                    f.document_id,
                    f.page_number,
                    d.title AS document_title,
                    d.filename
                FROM reviews r
                LEFT JOIN findings f
                    ON r.finding_id = f.id
                LEFT JOIN documents d
                    ON f.document_id = d.id
                ORDER BY r.id DESC
                LIMIT 100
                """
            ).fetchall()

        return {
            "monitoring_config": {
                "section_xpath": PRAC_SECTION_XPATH,
                "meeting_pdf_xpath": PRAC_MEETING_XPATH,
                "source_strategy": (
                    "Crawl the configured source URL and discover "
                    "all matching PRAC meeting-minute PDF links."
                )
            },

            "crawl_history": [
                dict(row)
                for row in crawl
            ],

            "extraction_history": [
                dict(row)
                for row in extraction
            ],

            "detection_history": [
                dict(row)
                for row in detection
            ],

            "summary_history": [
                dict(row)
                for row in summary
            ],

            "review_history": [
                dict(row)
                for row in reviews
            ]
        }

    except Exception as exc:
        logger.exception("History API failed")

        raise HTTPException(
            status_code=500,
            detail=f"History API failed: {str(exc)}"
        )



# ---------------------------------------------------------
# Summary PDF
# ---------------------------------------------------------

@app.get("/api/documents/{document_id}/summary-pdf")
def view_summary_pdf(document_id: int):

    try:

        pdf_path = create_document_summary_pdf(
            document_id
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    except Exception as exc:

        logger.exception(
            "Failed to create summary PDF for document %s",
            document_id,
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=pdf_path.name,
        content_disposition_type="inline",
    )


@app.get("/api/documents/{document_id}/summary-pdf/download")
def download_summary_pdf(document_id: int):

    try:

        pdf_path = create_document_summary_pdf(
            document_id
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    except Exception as exc:

        logger.exception(
            "Failed to create downloadable summary PDF "
            "for document %s",
            document_id,
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=pdf_path.name,
        content_disposition_type="attachment",
    )


# ---------------------------------------------------------
# Monitoring
# ---------------------------------------------------------

monitoring_jobs = {}


@app.post("/api/monitoring/run")
def start_monitoring(background_tasks: BackgroundTasks):

    job_id = str(uuid.uuid4())

    monitoring_jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "progress": 0,
        "message": "Monitoring job queued.",
        "documents_found": 0,
        "new_documents": 0,
        "findings_found": 0,
        "summary_pdfs_created": 0,
        "crawl_documents_discovered": 0,
        "pages_extracted": 0,
        "new_information": 0,
    }

    background_tasks.add_task(
        monitoring_worker,
        job_id,
    )

    return {
        "job_id": job_id,
        "status": "queued",
        "message": "Monitoring started.",
    }


@app.get("/api/monitoring/status/{job_id}")
def monitoring_status(job_id: str):

    job = monitoring_jobs.get(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Monitoring job not found.",
        )

    return job


# ---------------------------------------------------------
# Monitoring Worker
# ---------------------------------------------------------

def monitoring_worker(job_id: str):

    job = monitoring_jobs[job_id]

    try:

        job["status"] = "running"
        job["progress"] = 5
        job["message"] = "Loading active sources..."

        with get_db() as conn:
            sources = conn.execute(
                """
                SELECT *
                FROM sources
                WHERE active = 1
                ORDER BY id
                """
            ).fetchall()

        if not sources:
            job["status"] = "completed"
            job["progress"] = 100
            job["message"] = "No active sources configured."
            return

        total_documents_found = 0
        new_documents = 0
        total_findings = 0

        for source in sources:

            source_id = source["id"]

            job["progress"] = 10
            job["message"] = (
                f"Crawling {source['name']}..."
            )

            crawl_started = datetime.utcnow().isoformat()

            try:
                result = crawl_source(
                    str(source["url"]),
                    source_id=source["id"],
                    content_types=normalize_content_types(source.get("content_types")),
                    source_name=source.get("name"),
                    reference_no=source.get("reference_no"),
                )

                documents = result.get(
                    "documents",
                    []
                )

                total_documents_found += len(documents)
                job["crawl_documents_discovered"] = (
                    job.get("crawl_documents_discovered", 0)
                    + len(documents)
                )

                crawl_status = "success"
                crawl_error = None

            except Exception as exc:

                logger.exception(
                    "Crawler failed for source %s",
                    source_id,
                )

                documents = []
                crawl_status = "failed"
                crawl_error = str(exc)

            crawl_completed = datetime.utcnow().isoformat()

            with get_db() as conn:
                conn.execute(
                    """
                    INSERT INTO crawl_history
                    (
                        source_id,
                        started_at,
                        completed_at,
                        status,
                        documents_found,
                        error_message
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        crawl_started,
                        crawl_completed,
                        crawl_status,
                        len(documents),
                        crawl_error,
                    ),
                )

            # -------------------------------------------------
            # Process discovered documents
            # -------------------------------------------------

            for discovered in documents:

                url = discovered.get("url")

                if not url:
                    continue

                title = discovered.get(
                    "title",
                    "PRAC Meeting Minutes",
                )

                filename = discovered.get(
                    "filename"
                )

                meeting_date = discovered.get(
                    "meeting_date"
                )

                publication_date = discovered.get(
                    "publication_date"
                )

                content_type = discovered.get("content_type")
                discovered_date = datetime.utcnow().isoformat()

                with get_db() as conn:
                    existing_document_id = None

                    existing = conn.execute(
                        """
                        SELECT *
                        FROM documents
                        WHERE lower(rtrim(url, '/')) = lower(rtrim(?, '/'))
                        """,
                        (url,),
                    ).fetchone()

                    if existing:
                        previous_generated_reference = _document_reference_id(
                            source["reference_no"],
                            existing["publication_date"],
                            int(existing["id"]),
                        )
                        reference_id = existing["reference_id"]
                        if (
                            not reference_id
                            or reference_id == previous_generated_reference
                        ):
                            reference_id = _document_reference_id(
                                source["reference_no"],
                                publication_date,
                                int(existing["id"]),
                            )
                        conn.execute(
                            """
                            UPDATE documents
                            SET title = COALESCE(?, title),
                                publication_date = ?,
                                meeting_date = COALESCE(?, meeting_date),
                                content_type = COALESCE(?, content_type),
                                last_crawled_at = ?,
                                reference_id = ?
                            WHERE id = ?
                            """,
                            (
                                title,
                                publication_date,
                                meeting_date,
                                content_type,
                                discovered_date,
                                reference_id,
                                existing["id"],
                            ),
                        )
                        if str(existing["status"] or "").upper() in {
                            "PROCESSED",
                            "EXTRACTED",
                        }:
                            continue
                        existing_document_id = int(existing["id"])

                    # -----------------------------------------
                    # Download PDF
                    # -----------------------------------------

                    job["message"] = (
                        f"Downloading {title}..."
                    )

                    try:

                        download_result = download_pdf(
                            url,
                            PDF_DIR,
                        )

                        if isinstance(download_result, dict):
                            downloaded_path = download_result.get("path")
                            downloaded_filename = download_result.get(
                                "filename"
                            )
                            downloaded_sha256 = download_result.get(
                                "document_hash"
                            )
                        else:
                            downloaded_path = download_result
                            downloaded_filename = None
                            downloaded_sha256 = None

                    except Exception as exc:

                        logger.exception(
                            "PDF download failed: %s",
                            url,
                        )
                        if existing_document_id is not None:
                            conn.execute(
                                "UPDATE documents SET status = 'FAILED' WHERE id = ?",
                                (existing_document_id,),
                            )

                        continue

                    if not downloaded_path:
                        if existing_document_id is not None:
                            conn.execute(
                                "UPDATE documents SET status = 'FAILED' WHERE id = ?",
                                (existing_document_id,),
                            )
                        continue

                    downloaded_path = Path(
                        downloaded_path
                    )

                    if not downloaded_path.exists():
                        if existing_document_id is not None:
                            conn.execute(
                                "UPDATE documents SET status = 'FAILED' WHERE id = ?",
                                (existing_document_id,),
                            )
                        continue

                    filename = (
                        downloaded_filename
                        or downloaded_path.name
                        or filename
                    )

                    # -----------------------------------------
                    # Calculate hash
                    # -----------------------------------------

                    try:

                        if downloaded_sha256:
                            sha256 = downloaded_sha256
                        else:
                            import hashlib

                            sha256_hash = hashlib.sha256()

                            with open(
                                downloaded_path,
                                "rb",
                            ) as pdf_file:

                                for chunk in iter(
                                    lambda: pdf_file.read(1024 * 1024),
                                    b"",
                                ):
                                    sha256_hash.update(chunk)

                            sha256 = sha256_hash.hexdigest()

                    except Exception as exc:

                        logger.exception(
                            "Hash calculation failed"
                        )
                        if existing_document_id is not None:
                            conn.execute(
                                "UPDATE documents SET status = 'FAILED' WHERE id = ?",
                                (existing_document_id,),
                            )

                        continue

                    # -----------------------------------------
                    # Duplicate hash protection
                    # -----------------------------------------

                    duplicate = conn.execute(
                        """
                        SELECT id
                        FROM documents
                        WHERE sha256 = ?
                        """,
                        (sha256,),
                    ).fetchone()

                    if (
                        duplicate
                        and existing_document_id is None
                    ):
                        continue

                    # -----------------------------------------
                    # Save document metadata
                    # -----------------------------------------

                    if existing_document_id is not None:
                        document_id = existing_document_id
                        existing_reference_id = existing["reference_id"]
                        old_generated_reference = _document_reference_id(
                            source["reference_no"],
                            existing["publication_date"],
                            document_id,
                        )
                        reference_id = (
                            _document_reference_id(
                                source["reference_no"],
                                publication_date,
                                document_id,
                            )
                            if not existing_reference_id
                            or existing_reference_id == old_generated_reference
                            else existing_reference_id
                        )
                        conn.execute(
                            """
                            UPDATE documents
                            SET filename = ?,
                                sha256 = ?,
                                publication_date = ?,
                                content_type = COALESCE(?, content_type),
                                reference_id = ?,
                                status = 'NEW'
                            WHERE id = ?
                            """,
                            (
                                filename,
                                sha256,
                                publication_date,
                                content_type,
                                reference_id,
                                document_id,
                            ),
                        )
                    else:
                        cursor = conn.execute(
                            """
                            INSERT INTO documents
                            (
                                source_id,
                                title,
                                url,
                                meeting_date,
                                publication_date,
                                filename,
                                discovered_date,
                                last_crawled_at,
                                content_type,
                                sha256,
                                status,
                                created_at
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                source_id,
                                title,
                                url,
                                meeting_date,
                                publication_date,
                                filename,
                                discovered_date,
                                discovered_date,
                                content_type,
                                sha256,
                                "NEW",
                                datetime.utcnow().isoformat(),
                            ),
                        )

                        document_id = cursor.lastrowid
                        reference_id = _document_reference_id(
                            source["reference_no"],
                            publication_date,
                            document_id,
                        )
                        conn.execute(
                            "UPDATE documents SET reference_id = ? WHERE id = ?",
                            (reference_id, document_id),
                        )

                new_documents += 1

                # ---------------------------------------------
                # Extract PDF
                # ---------------------------------------------

                job["message"] = (
                    f"Extracting {title}..."
                )

                extraction_started = datetime.utcnow().isoformat()

                try:

                    pages = process_pdf_safe(
                        downloaded_path
                    )

                    extraction_status = "success"
                    extraction_error = None

                except Exception as exc:

                    logger.exception(
                        "PDF extraction failed for document %s",
                        document_id,
                    )

                    pages = []
                    extraction_status = "failed"
                    extraction_error = str(exc)

                pages_extracted = 0

                # ---------------------------------------------
                # Store pages
                # ---------------------------------------------

                with get_db() as conn:

                    for page in pages:

                        page_number = page.get(
                            "page_number"
                        )

                        page_text = page.get(
                            "text",
                            "",
                        )

                        if page_number is None:
                            continue

                        conn.execute(
                            """
                            INSERT OR REPLACE INTO document_pages
                            (
                                document_id,
                                page_number,
                                page_text,
                                created_at
                            )
                            VALUES (?, ?, ?, ?)
                            """,
                            (
                                document_id,
                                page_number,
                                page_text,
                                datetime.utcnow().isoformat(),
                            ),
                        )

                        pages_extracted += 1

                    conn.execute(
                        """
                        UPDATE documents
                        SET status = ?
                        WHERE id = ?
                        """,
                        (
                            "EXTRACTED"
                            if extraction_status == "success"
                            else "EXTRACTION_FAILED",
                            document_id,
                        ),
                    )

                    conn.execute(
                        """
                        INSERT INTO extraction_history
                        (
                            document_id,
                            started_at,
                            completed_at,
                            status,
                            pages_extracted,
                            error_message
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            document_id,
                            extraction_started,
                            datetime.utcnow().isoformat(),
                            extraction_status,
                            pages_extracted,
                            extraction_error,
                        ),
                    )

                # ---------------------------------------------
                # Detect safety findings
                # ---------------------------------------------

                if pages:

                    job["message"] = (
                        f"Detecting safety information in {title}..."
                    )

                    try:

                        findings = detect_document(
                            pages,
                            load_trigger_config(),
                        )

                    except Exception as exc:

                        logger.exception(
                            "Detection failed for document %s",
                            document_id,
                        )

                        findings = []

                    findings = remove_duplicate_findings(
                        findings
                    )

                    for finding in findings:

                        # Make sure document ID exists
                        finding["document_id"] = document_id

                        try:
                            comparison = compare_finding(
                                finding
                            )

                            if isinstance(
                                comparison,
                                dict,
                            ):
                                comparison_status = (
                                    comparison.get(
                                        "comparison_status",
                                        "NEW",
                                    )
                                )
                            else:
                                comparison_status = "NEW"

                        except Exception:

                            logger.exception(
                                "Comparison failed"
                            )

                            comparison_status = "NEW"

                        finding[
                            "comparison_status"
                        ] = comparison_status

                        with get_db() as conn:

                            cursor = conn.execute(
                                """
                                INSERT INTO findings
                                (
                                    document_id,
                                    page_number,
                                    product_name,
                                    active_substance,
                                    trigger_name,
                                    safety_topic,
                                    relevant_terms,
                                    evidence,
                                    section,
                                    comparison_status,
                                    evidence_hash,
                                    created_at
                                )
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    document_id,
                                    finding.get(
                                        "page_number"
                                    ),
                                    finding.get(
                                        "product_name"
                                    ),
                                    finding.get(
                                        "active_substance"
                                    ),
                                    finding.get(
                                        "trigger_name",
                                        load_trigger_config().get(
                                            "name",
                                            "Benzodiazepines",
                                        ),
                                    ),
                                    finding.get(
                                        "safety_topic"
                                    ),
                                    finding.get(
                                        "relevant_terms"
                                    ),
                                    finding.get(
                                        "evidence"
                                    ),
                                    finding.get(
                                        "section"
                                    ),
                                    comparison_status,
                                    finding.get(
                                        "evidence_hash"
                                    ),
                                    datetime.utcnow().isoformat(),
                                ),
                            )

                            finding_id = cursor.lastrowid

                        total_findings += 1

                job["findings_found"] = total_findings
                job["pages_extracted"] = (
                    job.get("pages_extracted", 0)
                    + pages_extracted
                )

                # -------------------------------------------------
                # Create document summary PDF
                # -------------------------------------------------
                try:
                    summary_pdf_path = create_document_summary_pdf(
                        document_id
                    )
                    job["summary_pdfs_created"] = (
                        job.get("summary_pdfs_created", 0) + 1
                    )
                    logger.info(
                        "Summary PDF created for document %s: %s",
                        document_id,
                        summary_pdf_path,
                    )
                except Exception:
                    logger.exception(
                        "Summary PDF generation failed for document %s",
                        document_id,
                    )

        # -----------------------------------------------------
        # Finished
        # -----------------------------------------------------

        job["status"] = "completed"
        job["progress"] = 100
        job["documents_found"] = total_documents_found
        job["new_documents"] = new_documents
        job["findings_found"] = total_findings

        with get_db() as conn:
            job["new_information"] = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM findings
                WHERE UPPER(COALESCE(comparison_status, ''))
                    IN ('NEW', 'NEW_INFORMATION')
                """
            ).fetchone()["count"]

        job["message"] = (
            "Monitoring completed successfully."
        )

        logger.info(
            "Monitoring job %s completed.",
            job_id,
        )

    except Exception as exc:

        logger.exception(
            "Monitoring job %s failed.",
            job_id,
        )

        job["status"] = "failed"
        job["message"] = str(exc)
        job["error"] = str(exc)


# ---------------------------------------------------------
# Manual document processing
# ---------------------------------------------------------

@app.post("/api/documents/{document_id}/process")
def process_document_endpoint(
    document_id: int,
):

    with get_db() as conn:
        document = conn.execute(
            """
            SELECT *
            FROM documents
            WHERE id = ?
            """,
            (document_id,),
        ).fetchone()

    if not document:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    filename = document["filename"]

    if not filename:
        raise HTTPException(
            status_code=404,
            detail="Document PDF filename missing.",
        )

    pdf_path = PDF_DIR / filename

    if not pdf_path.exists():
        raise HTTPException(
            status_code=404,
            detail="PDF file not found.",
        )

    try:

        processed = process_pdf_safe(pdf_path)
        if not processed.get("success"):
            raise HTTPException(
                status_code=422,
                detail=processed.get("error") or "PDF text extraction failed.",
            )
        pages = processed.get("pages", [])

        with get_db() as conn:

            for page in pages:

                conn.execute(
                    """
                    INSERT OR REPLACE INTO document_pages
                    (
                        document_id,
                        page_number,
                        page_text,
                        created_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        page["page_number"],
                        page.get("text", ""),
                        datetime.utcnow().isoformat(),
                    ),
                )

            conn.execute(
                """
                UPDATE documents
                SET status = 'EXTRACTED'
                WHERE id = ?
                """,
                (document_id,),
            )

        findings = detect_document(
            pages,
            load_trigger_config(),
        )

        findings = remove_duplicate_findings(
            findings
        )

        inserted = 0

        with get_db() as conn:

            for finding in findings:

                finding["document_id"] = document_id

                try:
                    comparison = compare_finding(
                        finding
                    )

                    if isinstance(
                        comparison,
                        dict,
                    ):
                        comparison_status = comparison.get(
                            "comparison_status",
                            "NEW",
                        )
                    else:
                        comparison_status = "NEW"

                except Exception:
                    comparison_status = "NEW"

                conn.execute(
                    """
                    INSERT INTO findings
                    (
                        document_id,
                        page_number,
                        product_name,
                        active_substance,
                        trigger_name,
                        safety_topic,
                        relevant_terms,
                        evidence,
                        section,
                        comparison_status,
                        evidence_hash,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        finding.get("page_number"),
                        finding.get("product_name"),
                        finding.get("active_substance"),
                        finding.get(
                            "trigger_name",
                            load_trigger_config().get(
                                "name",
                                "Benzodiazepines",
                            ),
                        ),
                        finding.get("safety_topic"),
                        finding.get("relevant_terms"),
                        finding.get("evidence"),
                        finding.get("section"),
                        comparison_status,
                        finding.get("evidence_hash"),
                        datetime.utcnow().isoformat(),
                    ),
                )

                inserted += 1

        # Create the same review-support summary PDF
        # for manually processed documents.
        summary_pdf_path = create_document_summary_pdf(
            document_id
        )

        return {
            "success": True,
            "document_id": document_id,
            "pages_extracted": len(pages),
            "findings_created": inserted,
            "summary_pdf": str(summary_pdf_path),
            "summary_pdf_view_url": (
                f"/api/documents/{document_id}/summary-pdf"
            ),
            "summary_pdf_download_url": (
                f"/api/documents/{document_id}/summary-pdf/download"
            ),
        }

    except Exception as exc:

        logger.exception(
            "Manual document processing failed."
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# ---------------------------------------------------------
# Storage
# ---------------------------------------------------------

@app.get("/api/storage")
def storage_info():

    pdf_files = list(
        PDF_DIR.glob("*.pdf")
    )

    total_size = sum(
        file.stat().st_size
        for file in pdf_files
        if file.exists()
    )

    return {
        "pdf_directory": str(PDF_DIR),
        "pdf_count": len(pdf_files),
        "total_bytes": total_size,
    }


# ---------------------------------------------------------
# Run locally
# ---------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
    )