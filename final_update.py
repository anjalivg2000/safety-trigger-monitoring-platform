from pathlib import Path

BASE = Path(__file__).resolve().parent
MAIN = BASE / "backend" / "main.py"
APP = BASE / "frontend" / "app.js"
INDEX = BASE / "frontend" / "index.html"
STYLE = BASE / "frontend" / "style.css"

# ============================================================
# MAIN.PY — FIX DASHBOARD HISTORY QUERY
# ============================================================

main = MAIN.read_text(encoding="utf-8")

main = main.replace(
'''        latest_crawl = conn.execute(
            """
            SELECT crawl_time
            FROM crawl_history
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()''',
'''        latest_crawl = conn.execute(
            """
            SELECT completed_at
            FROM crawl_history
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()'''
)

MAIN.write_text(main, encoding="utf-8")


# ============================================================
# MAIN.PY — PDF ENDPOINT
# ============================================================

main = MAIN.read_text(encoding="utf-8")

if '@app.get("/api/documents/{document_id}/pdf")' not in main:

    marker = '@app.get("/api/documents/{document_id}/pages")'

    endpoint = '''
@app.get("/api/documents/{document_id}/pdf")
def get_document_pdf(document_id: int):

    with get_db() as conn:
        row = conn.execute(
            """
            SELECT filename, url
            FROM documents
            WHERE id = ?
            """,
            (document_id,),
        ).fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Document not found."
        )

    filename = row["filename"]

    if not filename:
        raise HTTPException(
            status_code=404,
            detail="PDF filename unavailable."
        )

    pdf_path = PDF_DIR / filename

    if not pdf_path.exists():

        try:
            result = download_pdf(
                row["url"],
                PDF_DIR
            )

            if result:
                pdf_path = Path(result["path"])

        except Exception as exc:
            logger.exception(
                "PDF download failed: %s",
                exc
            )

    if not pdf_path.exists():
        raise HTTPException(
            status_code=404,
            detail="PDF file not available."
        )

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=filename
    )


'''

    if marker in main:
        main = main.replace(
            marker,
            endpoint + marker,
            1
        )

MAIN.write_text(main, encoding="utf-8")


# ============================================================
# INDEX.HTML — PDF SELECTOR
# ============================================================

index = INDEX.read_text(encoding="utf-8")

if 'id="monitoring-document-select"' not in index:

    marker = '<button class="button button-primary" id="run-monitoring-button"'

    selector = '''
<select
    id="monitoring-document-select"
    class="monitoring-document-select"
>
    <option value="">All new PRAC PDFs</option>
</select>

'''

    if marker in index:
        index = index.replace(
            marker,
            selector + marker,
            1
        )

INDEX.write_text(index, encoding="utf-8")


# ============================================================
# APP.JS — PDF SELECTOR
# ============================================================

app = APP.read_text(encoding="utf-8")

if "function populateMonitoringDocuments()" not in app:

    marker = "function renderDocuments(documents) {"

    helper = '''
function populateMonitoringDocuments() {

    const select =
        $("monitoring-document-select");

    if (!select) return;

    select.innerHTML = `
        <option value="">
            All new PRAC PDFs
        </option>

        ${allDocuments.map(doc => `
            <option value="${doc.id}">
                ${escapeHtml(
                    doc.title ||
                    doc.filename ||
                    "PRAC Minutes"
                )}
            </option>
        `).join("")}
    `;
}


'''

    if marker in app:
        app = app.replace(
            marker,
            helper + marker,
            1
        )


# Populate dropdown whenever documents load

needle = '''    renderDocuments(
        allDocuments
    );'''

replacement = '''    renderDocuments(
        allDocuments
    );

    populateMonitoringDocuments();'''

if needle in app and "populateMonitoringDocuments();" not in app:
    app = app.replace(
        needle,
        replacement,
        1
    )


# ============================================================
# APP.JS — SELECTED PDF MONITORING
# ============================================================

start = app.find("async function runMonitoring() {")

if start != -1:

    end = app.find(
        "\nfunction startMonitoringPolling()",
        start
    )

    if end != -1:

        new_function = '''async function runMonitoring() {

    const button =
        $("run-monitoring-button");

    const select =
        $("monitoring-document-select");

    const documentId =
        select && select.value
            ? Number(select.value)
            : null;

    try {

        if (button) {
            button.disabled = true;
            button.textContent = "Starting...";
        }

        showMonitoringBanner(
            true,
            0,
            documentId
                ? "Processing selected PRAC PDF..."
                : "Starting monitoring..."
        );

        const payload = documentId
            ? { document_id: documentId }
            : {};

        const result =
            await apiRequest(
                "/monitoring/run",
                {
                    method: "POST",
                    body: JSON.stringify(payload)
                }
            );

        monitoringJobId =
            result.job_id;

        showToast(
            documentId
                ? "Selected PDF processing started."
                : "Monitoring started.",
            "info"
        );

        startMonitoringPolling();

    } catch (error) {

        showMonitoringBanner(false);

        if (button) {
            button.disabled = false;
            button.textContent = "Run Monitoring";
        }

        showToast(
            error.message ||
            "Unable to start monitoring.",
            "error"
        );
    }
}


'''

        app = (
            app[:start]
            + new_function
            + app[end:]
        )


# ============================================================
# APP.JS — REAL LAST SYNC
# ============================================================

if "function formatDateTime(value)" not in app:

    marker = "function truncate(value"

    if marker in app:

        formatter = '''function formatDateTime(value) {

    if (!value) return "Not synced";

    try {
        return new Date(value).toLocaleString(
            "en-IN",
            {
                day: "2-digit",
                month: "short",
                year: "numeric",
                hour: "2-digit",
                minute: "2-digit"
            }
        );
    } catch {
        return value;
    }
}


'''

        app = app.replace(
            marker,
            formatter + marker,
            1
        )


APP.write_text(app, encoding="utf-8")


# ============================================================
# STYLE
# ============================================================

style = STYLE.read_text(encoding="utf-8")

if "monitoring-document-select" not in style:

    style += '''

.monitoring-document-select {
    min-width: 280px;
    height: 42px;
    padding: 0 14px;
    border: 1px solid #d0d5dd;
    border-radius: 8px;
    background: #fff;
    color: #101828;
    font-weight: 600;
    outline: none;
}

.monitoring-document-select:focus {
    border-color: #3b82f6;
    box-shadow: 0 0 0 3px rgba(59,130,246,.12);
}

'''

STYLE.write_text(style, encoding="utf-8")


print("")
print("=" * 60)
print("FINAL UPDATE COMPLETE")
print("=" * 60)
print("")
print("Now run:")
print("")
print(r".\venv\Scripts\python.exe -m py_compile backend\main.py")
print("")