"use strict";

/* ============================================================
   SAFETY TRIGGER MONITORING PLATFORM
   COMPLETE FRONTEND
   ============================================================ */

const API_BASE = "/api";

let allDocuments = [];
let allFindings = [];
let currentDocumentId = null;
let currentPageNumber = 1;
let currentPages = [];
let monitoringTimer = null;


/* ============================================================
   HELPERS
   ============================================================ */

function $(id) {
    return document.getElementById(id);
}


function escapeHtml(value) {
    if (value === null || value === undefined) {
        return "";
    }

    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


function formatDate(value) {

    if (!value) {
        return "—";
    }

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
        return String(value);
    }
}


function formatShortDate(value) {

    if (!value) {
        return "—";
    }

    try {
        return new Date(value).toLocaleDateString(
            "en-IN",
            {
                day: "2-digit",
                month: "short",
                year: "numeric"
            }
        );
    } catch {
        return String(value);
    }
}


function truncate(value, length = 120) {

    if (!value) {
        return "—";
    }

    const text = String(value);

    return text.length > length
        ? `${text.substring(0, length)}...`
        : text;
}


/* ============================================================
   API
   ============================================================ */

async function apiRequest(endpoint, options = {}) {

    const response = await fetch(
        `${API_BASE}${endpoint}`,
        {
            ...options,
            headers: {
                ...(options.body
                    ? {
                        "Content-Type":
                            "application/json"
                    }
                    : {}),
                ...(options.headers || {})
            }
        }
    );

    let data = null;

    try {
        data = await response.json();
    } catch {
        data = null;
    }

    if (!response.ok) {

        throw new Error(
            data?.detail ||
            data?.message ||
            `Request failed: ${response.status}`
        );
    }

    return data;
}


/* ============================================================
   TOAST
   ============================================================ */

function showToast(
    message,
    type = "info"
) {

    const container =
        $("toast-container");

    if (!container) {
        return;
    }

    const toast =
        document.createElement("div");

    toast.className =
        `toast ${type}`;

    toast.innerHTML =
        `<span>${escapeHtml(message)}</span>`;

    container.appendChild(toast);

    setTimeout(() => {

        toast.style.opacity = "0";

        setTimeout(
            () => toast.remove(),
            300
        );

    }, 3500);
}


/* ============================================================
   NAVIGATION
   ============================================================ */

function navigateTo(pageName) {

    document
        .querySelectorAll(".page")
        .forEach(page => {
            page.classList.remove("active");
        });

    const page =
        $(`page-${pageName}`);

    if (!page) {
        return;
    }

    page.classList.add("active");

    document
        .querySelectorAll(".nav-item")
        .forEach(item => {

            item.classList.toggle(
                "active",
                item.dataset.page === pageName
            );

        });

    const active =
        document.querySelector(
            `.nav-item[data-page="${pageName}"]`
        );

    if (active) {

        const label =
            active.querySelector(
                "span:last-child"
            );

        if (label && $("breadcrumb-current")) {

            $("breadcrumb-current")
                .textContent =
                label.textContent.trim();
        }
    }

    window.scrollTo({
        top: 0,
        behavior: "smooth"
    });

    const sidebar =
        $("sidebar");

    if (sidebar) {
        sidebar.classList.remove("open");
    }

    loadPageData(pageName);
}


async function loadPageData(pageName) {

    try {

        switch (pageName) {

            case "dashboard":
                await loadDashboard();
                break;

            case "sources":
                await loadSources();
                break;

            case "prac-minutes":
                await loadDocuments();
                break;

            case "new-information":
                await loadNewInformation();
                break;

            case "findings":
                await loadFindings();
                break;

            case "documents":
                await loadDocumentViewer();
                break;

            case "reviews":
                await loadReviews();
                break;

            case "configuration":
                await loadConfiguration();
                break;

            case "history":
                await loadHistory();
                break;
        }

    } catch (error) {

        console.error(
            `Page load error (${pageName}):`,
            error
        );

        showToast(
            `Unable to load ${pageName}.`,
            "error"
        );
    }
}


/* ============================================================
   DASHBOARD
   ============================================================ */

async function loadDashboard() {

    const data =
        await apiRequest(
            "/dashboard"
        );

    if ($("kpi-sources")) {
        $("kpi-sources").textContent =
            data.sources ?? 0;
    }

    if ($("kpi-documents")) {
        $("kpi-documents").textContent =
            data.documents ?? 0;
    }

    if ($("kpi-new-information")) {
        $("kpi-new-information")
            .textContent =
            data.new_information ?? 0;
    }

    if ($("kpi-findings")) {
        $("kpi-findings").textContent =
            data.findings ?? 0;
    }

    if ($("new-information-badge")) {
        $("new-information-badge")
            .textContent =
            data.new_information ?? 0;
    }

    await loadDashboardFindings();

    await checkOllamaStatus();
}


async function loadDashboardFindings() {

    const findings =
        await apiRequest(
            "/findings/new"
        );

    const container =
        $("dashboard-findings");

    if (!container) {
        return;
    }

    if (!findings.length) {

        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">✓</div>
                <h4>No new information</h4>
                <p>
                    Run monitoring to check
                    the latest PRAC minutes.
                </p>
            </div>
        `;

        return;
    }

    container.innerHTML = `
        <table class="data-table">

            <thead>
                <tr>
                    <th>Product</th>
                    <th>Active Substance</th>
                    <th>Safety Topic</th>
                    <th>Page</th>
                    <th>Status</th>
                </tr>
            </thead>

            <tbody>

                ${findings.slice(0, 10).map(
                    finding => `

                    <tr
                        class="clickable-row"
                        data-finding-id="${finding.id}"
                    >

                        <td class="primary-cell">
                            ${escapeHtml(
                                finding.product_name ||
                                "Not identified"
                            )}
                        </td>

                        <td>
                            ${escapeHtml(
                                finding.active_substance ||
                                "—"
                            )}
                        </td>

                        <td>
                            ${escapeHtml(
                                finding.safety_topic ||
                                "—"
                            )}
                        </td>

                        <td>
                            ${finding.page_number ?? "—"}
                        </td>

                        <td>
                            ${comparisonBadge(
                                finding.comparison_status
                            )}
                        </td>

                    </tr>
                `
                ).join("")}

            </tbody>

        </table>
    `;
}


/* ============================================================
   SOURCES
   ============================================================ */

async function loadSources() {

    const [sources, history] =
        await Promise.all([
            apiRequest("/sources"),
            apiRequest("/history")
        ]);

    const container =
        $("sources-table");

    if (!container) {
        return;
    }

    if (!sources.length) {

        container.innerHTML = `
            <div class="empty-state">
                <h4>No data crawler sources configured</h4>
            </div>
        `;

        return;
    }

    const crawlHistory =
        history.crawl_history || [];

    container.innerHTML = `

        <table class="data-table">

            <thead>
                <tr>
                    <th>ID</th>
                    <th>Region</th>
                    <th>Frequency</th>
                    <th>Website</th>
                    <th>Content Type</th>
                    <th>URL</th>
                    <th>Last Crawled</th>
                    <th>Status</th>
                    <th>Action</th>
                </tr>
            </thead>

            <tbody>

                ${sources.map(
                    source => {

                        const last =
                            crawlHistory.find(
                                row =>
                                    Number(row.source_id) === Number(source.id)
                            );

                        const contentTypes = Array.isArray(source.content_types)
                            ? source.content_types.join(", ")
                            : (source.content_types || source.safety_alert_type || "—");

                        return `

                            <tr>

                                <td class="primary-cell">
                                    ${escapeHtml(source.reference_no || source.id || "—")}
                                </td>

                                <td>
                                    ${escapeHtml(source.region || "EEA")}
                                </td>

                                <td>
                                    ${escapeHtml(source.monitoring_frequency || "Monthly")}
                                </td>

                                <td>
                                    ${escapeHtml(source.website || "EMA")}
                                </td>

                                <td>
                                    ${escapeHtml(contentTypes)}
                                </td>

                                <td>
                                    <a
                                        href="${escapeHtml(source.url)}"
                                        target="_blank"
                                        rel="noopener"
                                    >
                                        Open ↗
                                    </a>
                                </td>

                                <td>
                                    ${last ? formatDate(last.completed_at || last.started_at) : "Not run"}
                                </td>

                                <td>
                                    ${statusBadge(last?.status || (source.active ? "Active" : "Inactive"))}
                                </td>

                                <td>
                                    <div style="display:flex; gap:6px; flex-wrap:wrap;">
                                        <button
                                            class="button button-primary"
                                            onclick="runSourceCrawl(${source.id})"
                                        >
                                            Run Crawl
                                        </button>
                                        <button
                                            class="button button-secondary"
                                            onclick="testConfiguredSource('${escapeHtml(source.url)}')"
                                        >
                                            Test
                                        </button>
                                    </div>
                                </td>

                            </tr>

                        `;
                    }
                ).join("")}

            </tbody>

        </table>
    `;
}


async function runSourceCrawl(sourceId) {

    try {
        const result =
            await apiRequest(
                "/crawl/run",
                {
                    method: "POST",
                    body: JSON.stringify({
                        source_id: Number(sourceId)
                    })
                }
            );

        showToast(
            `${result.documents_found ?? 0} document(s) found; ${result.new_documents ?? 0} new.`,
            "success"
        );

        await loadSources();

    } catch (error) {
        showToast(
            error.message || "Crawl failed.",
            "error"
        );
    }
}


async function runAllActiveCrawls() {

    try {
        const result = await apiRequest("/monitoring/run", {
            method: "POST"
        });

        showToast(
            result.message || "Monitoring job started for active sources.",
            "success"
        );

    } catch (error) {
        showToast(
            error.message || "Unable to start active source crawl.",
            "error"
        );
    }
}


function openSourceModal() {
    const modal = document.getElementById("sourceModal");
    if (modal) {
        modal.style.display = "flex";
    }
}


function closeSourceModal() {
    const modal = document.getElementById("sourceModal");
    if (modal) {
        modal.style.display = "none";
    }
}


async function createSource() {

    const authority = document.getElementById("sourceAuthority").value.trim();
    const name = document.getElementById("sourceName").value.trim();
    const referenceNo = document.getElementById("sourceReferenceNo").value.trim();
    const region = document.getElementById("sourceRegion").value.trim() || "EEA";
    const monitoringFrequency = document.getElementById("sourceFrequency").value.trim() || "Monthly";
    const website = document.getElementById("sourceWebsite").value.trim() || "EMA";
    const safetyAlertType = document.getElementById("sourceSafetyAlertType").value.trim() || "PRAC";
    const sourceType = document.getElementById("sourceType").value.trim() || "Health Authority";
    const contentRaw = document.getElementById("sourceContentTypes").value.trim();
    const contentTypes = contentRaw ? contentRaw.split(",").map(part => part.trim()).filter(Boolean) : [safetyAlertType];
    const url = document.getElementById("sourceUrl").value.trim();

    if (!authority || !name || !url) {
        showToast("Authority, source name, and URL are required.", "error");
        return;
    }

    try {
        const result = await apiRequest("/sources", {
            method: "POST",
            body: JSON.stringify({
                reference_no: referenceNo,
                authority,
                name,
                source_type: sourceType,
                region,
                monitoring_frequency: monitoringFrequency,
                website,
                safety_alert_type: safetyAlertType,
                url,
                content_types: contentTypes,
                active: true
            })
        });

        showToast(result.message || "Source created successfully.", "success");
        closeSourceModal();
        await loadSources();

    } catch (error) {
        showToast(error.message || "Unable to create source.", "error");
    }
}


async function testConfiguredSource(url) {

    try {

        const result =
            await apiRequest(
                "/sources/test",
                {
                    method: "POST",
                    body: JSON.stringify({
                        url
                    })
                }
            );

        if (result.success) {

            showToast(
                `Source OK — ${result.pdf_links_found ?? 0} meeting PDF(s) found.`,
                "success"
            );

        } else {

            showToast(
                result.message ||
                "Source test unsuccessful.",
                "error"
            );
        }

    } catch (error) {

        showToast(
            error.message,
            "error"
        );
    }
}


/* ============================================================
   PRAC DOCUMENTS
   ============================================================ */

async function loadDocuments() {

    allDocuments =
        await apiRequest(
            "/documents"
        );

    renderDocuments(
        allDocuments
    );

    if ($("document-count")) {

        $("document-count")
            .textContent =
            `${allDocuments.length} document${
                allDocuments.length === 1
                    ? ""
                    : "s"
            }`;
    }
}


function renderDocuments(
    documents
) {

    const container =
        $("documents-table");

    if (!container) {
        return;
    }

    if (!documents.length) {

        container.innerHTML = `
            <div class="empty-state large">
                <div class="empty-icon">▤</div>
                <h4>No PRAC minutes discovered</h4>
                <p>
                    Run monitoring to discover
                    meeting minutes.
                </p>
            </div>
        `;

        return;
    }

    container.innerHTML = `

        <table class="data-table">

            <thead>
                <tr>
                    <th>Meeting</th>
                    <th>Meeting Date</th>
                    <th>Publication Date</th>
                    <th>Status</th>
                    <th>Pages</th>
                    <th>Actions</th>
                </tr>
            </thead>

            <tbody>

                ${documents.map(
                    document => `

                    <tr>

                        <td>

                            <div class="primary-cell">
                                ${escapeHtml(
                                    document.title ||
                                    document.filename ||
                                    "PRAC Minutes"
                                )}
                            </div>

                            <div class="secondary-cell">
                                ${escapeHtml(
                                    document.filename ||
                                    "—"
                                )}
                            </div>

                        </td>

                        <td>
                            ${formatShortDate(
                                document.meeting_date
                            )}
                        </td>

                        <td>
                            ${formatShortDate(
                                document.publication_date
                            )}
                        </td>

                        <td>
                            ${documentStatusBadge(
                                document.status
                            )}
                        </td>

                        <td>
                            <span
                                id="pages-${document.id}"
                            >
                                —
                            </span>
                        </td>

                        <td>

                            <div
                                style="
                                    display:flex;
                                    gap:6px;
                                    flex-wrap:wrap;
                                "
                            >

                                <button
                                    class="button button-secondary"
                                    onclick="openDocument(${document.id})"
                                >
                                    View
                                </button>

                                <a
                                    class="button button-secondary"
                                    href="/api/documents/${document.id}/pdf"
                                    target="_blank"
                                >
                                    PDF
                                </a>

                                <a
                                    class="button button-primary"
                                    href="/api/documents/${document.id}/summary-pdf"
                                    target="_blank"
                                >
                                    Summary
                                </a>

                                <a
                                    class="button button-primary"
                                    href="/api/documents/${document.id}/summary-pdf/download"
                                >
                                    Download Summary
                                </a>

                            </div>

                        </td>

                    </tr>

                `
                ).join("")}

            </tbody>

        </table>
    `;

    loadPageCounts(documents);
}


async function loadPageCounts(
    documents
) {

    for (const document of documents) {

        try {

            const pages =
                await apiRequest(
                    `/documents/${document.id}/pages`
                );

            const element =
                $(`pages-${document.id}`);

            if (element) {
                element.textContent =
                    pages.length;
            }

        } catch {
            // Keep UI stable if page count fails.
        }
    }
}


function documentStatusBadge(
    status
) {

    const value =
        String(
            status || ""
        ).toUpperCase();

    if (
        value === "EXTRACTED" ||
        value === "PROCESSED"
    ) {

        return `
            <span class="badge badge-success">
                ${escapeHtml(status)}
            </span>
        `;
    }

    if (
        value === "NEW"
    ) {

        return `
            <span class="badge badge-warning">
                NEW
            </span>
        `;
    }

    if (
        value.includes("FAILED")
    ) {

        return `
            <span class="badge badge-danger">
                ${escapeHtml(status)}
            </span>
        `;
    }

    return `
        <span class="badge badge-neutral">
            ${escapeHtml(status || "Unknown")}
        </span>
    `;
}


function filterDocuments(
    query
) {

    const value =
        query.trim().toLowerCase();

    if (!value) {

        renderDocuments(
            allDocuments
        );

        return;
    }

    const filtered =
        allDocuments.filter(
            document => {

                const text = [
                    document.title,
                    document.filename,
                    document.meeting_date,
                    document.publication_date,
                    document.status
                ]
                    .filter(Boolean)
                    .join(" ")
                    .toLowerCase();

                return text.includes(
                    value
                );
            }
        );

    renderDocuments(
        filtered
    );
}


/* ============================================================
   NEW INFORMATION
   ============================================================ */

async function loadNewInformation() {

    const findings =
        await apiRequest(
            "/findings/new"
        );

    const container =
        $("new-information-list");

    if (!container) {
        return;
    }

    if (!findings.length) {

        container.innerHTML = `
            <div class="empty-state large">
                <div class="empty-icon">✓</div>
                <h4>No new safety information</h4>
                <p>
                    No findings are currently
                    marked as new information.
                </p>
            </div>
        `;

        return;
    }

    renderFindingCards(
        findings,
        container
    );
}


function renderFindingCards(
    findings,
    container
) {

    container.innerHTML =
        findings.map(
            finding => `

            <article
                class="panel"
                style="margin-bottom:16px;"
            >

                <div class="panel-header">

                    <div>

                        <span class="panel-eyebrow">
                            SAFETY FINDING
                        </span>

                        <h3>
                            ${escapeHtml(
                                finding.product_name ||
                                "Product not identified"
                            )}
                        </h3>

                    </div>

                    ${comparisonBadge(
                        finding.comparison_status
                    )}

                </div>


                <div
                    style="
                        display:grid;
                        grid-template-columns:
                            repeat(auto-fit,minmax(180px,1fr));
                        gap:12px;
                        margin-top:16px;
                    "
                >

                    <div class="configuration-item">
                        <span>Active Substance</span>
                        <strong>
                            ${escapeHtml(
                                finding.active_substance ||
                                "—"
                            )}
                        </strong>
                    </div>

                    <div class="configuration-item">
                        <span>Safety Topic</span>
                        <strong>
                            ${escapeHtml(
                                finding.safety_topic ||
                                "—"
                            )}
                        </strong>
                    </div>

                    <div class="configuration-item">
                        <span>Page</span>
                        <strong>
                            ${finding.page_number ?? "—"}
                        </strong>
                    </div>

                    <div class="configuration-item">
                        <span>Trigger</span>
                        <strong>
                            ${escapeHtml(
                                finding.trigger_name ||
                                "—"
                            )}
                        </strong>
                    </div>

                </div>


                <div
                    style="
                        margin-top:18px;
                        padding:16px;
                        border:1px solid #e5e7eb;
                        border-radius:8px;
                    "
                >

                    <strong>
                        Evidence
                    </strong>

                    <p>
                        ${escapeHtml(
                            finding.evidence ||
                            "No evidence available."
                        )}
                    </p>

                </div>


                <div
                    style="
                        display:flex;
                        gap:8px;
                        flex-wrap:wrap;
                        margin-top:16px;
                    "
                >

                    <button
                        class="button button-secondary"
                        onclick="openFindingEvidence(${finding.id})"
                    >
                        View Evidence
                    </button>

                    <button
                        class="button button-secondary"
                        onclick="openDocument(${finding.document_id})"
                    >
                        Open PDF
                    </button>

                    <button
                        class="button button-primary"
                        onclick="showReviewModal(${finding.id})"
                    >
                        Review
                    </button>

                </div>

            </article>

        `
        ).join("");
}


function comparisonBadge(
    status
) {

    const value =
        String(
            status || ""
        ).toUpperCase();

    if (
        value === "NEW" ||
        value === "NEW_INFORMATION"
    ) {

        return `
            <span class="badge badge-warning">
                NEW INFORMATION
            </span>
        `;
    }

    if (
        value === "NO_NEW_INFORMATION"
    ) {

        return `
            <span class="badge badge-neutral">
                NO NEW INFORMATION
            </span>
        `;
    }

    return `
        <span class="badge badge-info">
            ${escapeHtml(
                status || "Not compared"
            )}
        </span>
    `;
}


/* ============================================================
   FINDINGS
   ============================================================ */

async function loadFindings() {

    allFindings =
        await apiRequest(
            "/findings"
        );

    const container =
        $("findings-table");

    if (!container) {
        return;
    }

    if (!allFindings.length) {

        container.innerHTML = `
            <div class="empty-state large">
                <div class="empty-icon">⌁</div>
                <h4>No safety findings</h4>
                <p>
                    Findings appear after
                    document processing.
                </p>
            </div>
        `;

        return;
    }

    container.innerHTML = `

        <table class="data-table">

            <thead>

                <tr>
                    <th>Product</th>
                    <th>Substance</th>
                    <th>Safety Topic</th>
                    <th>Trigger</th>
                    <th>Page</th>
                    <th>Comparison</th>
                    <th>Evidence</th>
                </tr>

            </thead>

            <tbody>

                ${allFindings.map(
                    finding => `

                    <tr>

                        <td class="primary-cell">
                            ${escapeHtml(
                                finding.product_name ||
                                "Not identified"
                            )}
                        </td>

                        <td>
                            ${escapeHtml(
                                finding.active_substance ||
                                "—"
                            )}
                        </td>

                        <td>
                            ${escapeHtml(
                                finding.safety_topic ||
                                "—"
                            )}
                        </td>

                        <td>
                            ${escapeHtml(
                                finding.trigger_name ||
                                "—"
                            )}
                        </td>

                        <td>
                            ${finding.page_number ?? "—"}
                        </td>

                        <td>
                            ${comparisonBadge(
                                finding.comparison_status
                            )}
                        </td>

                        <td>

                            <button
                                class="button button-secondary"
                                onclick="openFindingEvidence(${finding.id})"
                            >
                                View
                            </button>

                        </td>

                    </tr>

                `
                ).join("")}

            </tbody>

        </table>
    `;
}


async function openFindingEvidence(
    findingId
) {

    try {

        const finding =
            await apiRequest(
                `/findings/${findingId}`
            );

        navigateTo(
            "documents"
        );

        setTimeout(
            () => {

                openDocument(
                    finding.document_id,
                    finding.page_number
                );

            },
            300
        );

    } catch (error) {

        showToast(
            error.message,
            "error"
        );
    }
}


/* ============================================================
   DOCUMENT VIEWER
   ============================================================ */

async function loadDocumentViewer() {

    const documents =
        await apiRequest(
            "/documents"
        );

    const list =
        $("viewer-document-list");

    if (!list) {
        return;
    }

    if (!documents.length) {

        list.innerHTML = `
            <div class="empty-state">
                <h4>No documents</h4>
                <p>
                    Run monitoring first.
                </p>
            </div>
        `;

        return;
    }

    list.innerHTML =
        documents.map(
            document => `

            <button
                class="document-list-item"
                data-document-id="${document.id}"
                onclick="openDocument(${document.id})"
                style="
                    width:100%;
                    text-align:left;
                    padding:14px;
                    margin-bottom:8px;
                    border:1px solid #e5e7eb;
                    border-radius:8px;
                    background:white;
                    cursor:pointer;
                "
            >

                <strong>
                    ${escapeHtml(
                        document.title ||
                        document.filename
                    )}
                </strong>

                <small>
                    Meeting:
                    ${escapeHtml(
                        document.meeting_date ||
                        "—"
                    )}
                </small>

            </button>

        `
        ).join("");
}


async function openDocument(
    documentId,
    pageNumber = 1
) {

    currentDocumentId =
        Number(documentId);

    currentPageNumber =
        Number(pageNumber) || 1;

    navigateTo(
        "documents"
    );

    try {

        const document =
            await apiRequest(
                `/documents/${documentId}`
            );

        currentPages =
            await apiRequest(
                `/documents/${documentId}/pages`
            );

        const title =
            $("viewer-title");

        if (title) {

            title.textContent =
                document.title ||
                document.filename ||
                "PRAC Meeting Minutes";
        }

        renderViewerActions(
            document
        );

        await renderCurrentViewerPage();

    } catch (error) {

        console.error(
            "Document viewer error:",
            error
        );

        showToast(
            error.message,
            "error"
        );
    }
}


function renderViewerActions(
    document
) {

    const panel =
        document.querySelector(
            "#page-documents .evidence-panel"
        );

    if (!panel) {
        return;
    }

    let actions =
        $("viewer-actions");

    if (!actions) {

        actions =
            document.createElement(
                "div"
            );

        actions.id =
            "viewer-actions";

        actions.style.display =
            "flex";

        actions.style.gap =
            "8px";

        actions.style.flexWrap =
            "wrap";

        actions.style.marginTop =
            "12px";

        const header =
            panel.querySelector(
                ".panel-header"
            );

        if (header) {
            header.appendChild(
                actions
            );
        }
    }

    actions.innerHTML = `

        <a
            class="button button-secondary"
            href="/api/documents/${currentDocumentId}/pdf"
            target="_blank"
            rel="noopener"
        >
            Open Original PDF
        </a>

        <a
            class="button button-secondary"
            href="/api/documents/${currentDocumentId}/summary-pdf"
            target="_blank"
            rel="noopener"
        >
            View Summary PDF
        </a>

        <a
            class="button button-primary"
            href="/api/documents/${currentDocumentId}/summary-pdf/download"
        >
            Download Summary PDF
        </a>

    `;
}


async function renderCurrentViewerPage() {

    const content =
        $("viewer-content");

    if (!content) {
        return;
    }

    if (!currentPages.length) {

        content.innerHTML = `
            <div class="empty-state">
                <h4>No extracted pages</h4>
                <p>
                    This document has not been
                    successfully extracted.
                </p>
            </div>
        `;

        return;
    }

    if (
        currentPageNumber < 1
    ) {
        currentPageNumber = 1;
    }

    if (
        currentPageNumber >
        currentPages.length
    ) {
        currentPageNumber =
            currentPages.length;
    }

    const page =
        currentPages.find(
            item =>
                Number(
                    item.page_number
                ) ===
                currentPageNumber
        ) ||
        currentPages[
            currentPageNumber - 1
        ];

    const actualPage =
        page?.page_number ??
        currentPageNumber;

    currentPageNumber =
        Number(actualPage);

    if ($("viewer-page")) {

        $("viewer-page")
            .textContent =
            `Page ${currentPageNumber} of ${currentPages.length}`;
    }

    content.innerHTML = `

        <div
            style="
                display:flex;
                justify-content:space-between;
                align-items:center;
                gap:8px;
                flex-wrap:wrap;
                margin-bottom:16px;
            "
        >

            <button
                class="button button-secondary"
                onclick="previousViewerPage()"
                ${currentPageNumber <= 1 ? "disabled" : ""}
            >
                ← Previous
            </button>

            <strong>
                Page ${currentPageNumber}
                / ${currentPages.length}
            </strong>

            <button
                class="button button-secondary"
                onclick="nextViewerPage()"
                ${
                    currentPageNumber >=
                    currentPages.length
                        ? "disabled"
                        : ""
                }
            >
                Next →
            </button>

        </div>


        <div
            style="
                background:white;
                border:1px solid #e5e7eb;
                border-radius:10px;
                padding:24px;
                white-space:pre-wrap;
                line-height:1.7;
                max-height:700px;
                overflow:auto;
            "
        >

            ${escapeHtml(
                page?.page_text ||
                "No text extracted for this page."
            )}

        </div>

    `;
}


function previousViewerPage() {

    if (
        currentPageNumber <= 1
    ) {
        return;
    }

    currentPageNumber--;

    renderCurrentViewerPage();
}


function nextViewerPage() {

    if (
        currentPageNumber >=
        currentPages.length
    ) {
        return;
    }

    currentPageNumber++;

    renderCurrentViewerPage();
}


/* ============================================================
   REVIEWS
   ============================================================ */

async function loadReviews() {

    const rows =
        await apiRequest(
            "/reviews"
        );

    const container =
        $("review-queue");

    if (!container) {
        return;
    }

    if (!rows.length) {

        container.innerHTML = `
            <div class="empty-state large">
                <div class="empty-icon">✓</div>
                <h4>No reviewer decisions yet</h4>
                <p>
                    Human review decisions
                    will appear here.
                </p>
            </div>
        `;

        return;
    }

    container.innerHTML = `

        <div class="panel">

            <div class="panel-header">

                <div>
                    <span class="panel-eyebrow">
                        REVIEW AUDIT
                    </span>

                    <h3>
                        Reviewer History
                    </h3>
                </div>

                <span class="badge badge-success">
                    ${rows.length} reviews
                </span>

            </div>


            <div
                style="
                    overflow-x:auto;
                    margin-top:16px;
                "
            >

                <table class="data-table">

                    <thead>

                        <tr>
                            <th>Finding</th>
                            <th>Product</th>
                            <th>Reviewer</th>
                            <th>Decision</th>
                            <th>Comments</th>
                            <th>Reviewed</th>
                        </tr>

                    </thead>

                    <tbody>

                        ${rows.map(
                            row => `

                            <tr>

                                <td>
                                    #${row.finding_id}
                                </td>

                                <td>
                                    ${escapeHtml(
                                        row.product_name ||
                                        "—"
                                    )}
                                </td>

                                <td>
                                    ${escapeHtml(
                                        row.reviewer ||
                                        "—"
                                    )}
                                </td>

                                <td>
                                    ${reviewBadge(
                                        row.decision
                                    )}
                                </td>

                                <td>
                                    ${escapeHtml(
                                        row.comments ||
                                        "—"
                                    )}
                                </td>

                                <td>
                                    ${formatDate(
                                        row.reviewed_at
                                    )}
                                </td>

                            </tr>

                        `
                        ).join("")}

                    </tbody>

                </table>

            </div>

        </div>
    `;
}


function showReviewModal(
    findingId
) {

    const overlay =
        $("modal-overlay");

    const body =
        $("modal-body");

    const title =
        $("modal-title");

    if (!overlay || !body) {
        return;
    }

    if (title) {
        title.textContent =
            `Review Finding #${findingId}`;
    }

    body.innerHTML = `

        <form
            id="review-form"
            onsubmit="submitReview(event, ${findingId})"
        >

            <div class="form-group">

                <label>
                    Reviewer
                </label>

                <input
                    id="reviewer-name"
                    required
                    value="PV Reviewer"
                    style="width:100%;"
                >

            </div>


            <div class="form-group">

                <label>
                    Decision
                </label>

                <select
                    id="review-decision"
                    required
                    style="width:100%;"
                >

                    <option value="">
                        Select decision
                    </option>

                    <option value="RELEVANT">
                        Relevant
                    </option>

                    <option value="NOT_RELEVANT">
                        Not relevant
                    </option>

                    <option value="DUPLICATE">
                        Duplicate
                    </option>

                    <option value="REQUIRES_FURTHER_REVIEW">
                        Requires further review
                    </option>

                </select>

            </div>


            <div class="form-group">

                <label>
                    Comments
                </label>

                <textarea
                    id="review-comments"
                    rows="5"
                    style="width:100%;"
                    placeholder="Reviewer comments..."
                ></textarea>

            </div>


            <button
                class="button button-primary"
                type="submit"
            >
                Record Review
            </button>

        </form>
    `;

    overlay.classList.remove(
        "hidden"
    );
}


async function submitReview(
    event,
    findingId
) {

    event.preventDefault();

    const reviewer =
        $("reviewer-name")?.value;

    const decision =
        $("review-decision")?.value;

    const comments =
        $("review-comments")?.value;

    if (!decision) {
        showToast(
            "Please select a decision.",
            "error"
        );
        return;
    }

    try {

        await apiRequest(
            "/reviews",
            {
                method: "POST",
                body: JSON.stringify({
                    finding_id:
                        Number(findingId),
                    reviewer,
                    decision,
                    comments
                })
            }
        );

        closeModal();

        showToast(
            "Review recorded successfully.",
            "success"
        );

        await loadReviews();

        await loadDashboard();

    } catch (error) {

        showToast(
            error.message,
            "error"
        );
    }
}


function reviewBadge(
    decision
) {

    const value =
        String(
            decision || ""
        ).toUpperCase();

    if (
        value === "RELEVANT"
    ) {
        return `
            <span class="badge badge-success">
                Relevant
            </span>
        `;
    }

    if (
        value === "NOT_RELEVANT"
    ) {
        return `
            <span class="badge badge-neutral">
                Not relevant
            </span>
        `;
    }

    if (
        value === "DUPLICATE"
    ) {
        return `
            <span class="badge badge-warning">
                Duplicate
            </span>
        `;
    }

    return `
        <span class="badge badge-info">
            ${escapeHtml(
                decision || "Unknown"
            )}
        </span>
    `;
}


function closeModal() {

    const overlay =
        $("modal-overlay");

    if (overlay) {
        overlay.classList.add(
            "hidden"
        );
    }
}


/* ============================================================
   CONFIGURATION
   ============================================================ */

const SOURCE_CONTENT_OPTIONS = [
    "Meeting Minutes",
    "Agendas",
    "Highlights",
    "PRAC recommendation on signals",
];

function renderSourceConfigurationCards(sources) {

    if (!Array.isArray(sources) || !sources.length) {
        return `
            <div class="empty-state">
                <h4>No website sources configured</h4>
            </div>
        `;
    }

    return `
        <div class="config-section-header">
            <div class="card-title">
                Website / Safety Alert Configuration
            </div>
            <button
                class="btn btn-primary"
                onclick="openSourceModal()"
            >
                + Add Source
            </button>
        </div>

        <div class="stacked-config">
            ${sources.map(source => {
                const selectedContent = new Set(
                    Array.isArray(source.content_types)
                        ? source.content_types
                        : []
                );

                return `
                    <div class="config-source-card" data-source-card="${source.id}">
                        <div class="config-source-header">
                            <div>
                                <div class="config-source-id">
                                    ${escapeHtml(source.reference_no || source.id || "—")}
                                </div>
                                <div class="config-source-name">
                                    ${escapeHtml(source.name || "Configured source")}
                                </div>
                            </div>
                            <label class="toggle-inline">
                                <input
                                    type="checkbox"
                                    data-source-field="active"
                                    ${source.active ? "checked" : ""}
                                >
                                Active
                            </label>
                        </div>

                        <div class="form-grid compact-grid">
                            <div class="form-group">
                                <label>ID / Reference No.</label>
                                <input data-source-field="reference_no" value="${escapeHtml(source.reference_no || "")}">
                            </div>
                            <div class="form-group">
                                <label>Name</label>
                                <input data-source-field="name" value="${escapeHtml(source.name || "Configured source")}">
                            </div>
                            <div class="form-group">
                                <label>Region</label>
                                <input data-source-field="region" value="${escapeHtml(source.region || "EEA")}">
                            </div>
                            <div class="form-group">
                                <label>Monitoring Frequency</label>
                                <select data-source-field="monitoring_frequency">
                                    <option ${source.monitoring_frequency === "Daily" ? "selected" : ""}>Daily</option>
                                    <option ${source.monitoring_frequency === "Weekly" ? "selected" : ""}>Weekly</option>
                                    <option ${source.monitoring_frequency === "Monthly" || !source.monitoring_frequency ? "selected" : ""}>Monthly</option>
                                    <option ${source.monitoring_frequency === "Yearly" ? "selected" : ""}>Yearly</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label>Website / Health Authority</label>
                                <input data-source-field="website" value="${escapeHtml(source.website || "EMA")}">
                            </div>
                            <div class="form-group">
                                <label>Safety Alert Type</label>
                                <input data-source-field="safety_alert_type" value="${escapeHtml(source.safety_alert_type || "PRAC")}">
                            </div>
                            <div class="form-group">
                                <label>Source Type</label>
                                <input data-source-field="source_type" value="${escapeHtml(source.source_type || "Health Authority")}">
                            </div>
                            <div class="form-group" style="grid-column: 1 / -1;">
                                <label>URL</label>
                                <input data-source-field="url" value="${escapeHtml(source.url || "")}">
                            </div>
                            <div class="form-group" style="grid-column: 1 / -1;">
                                <label>Instruction</label>
                                <textarea data-source-field="instruction">${escapeHtml(source.instruction || "")}</textarea>
                            </div>
                            <div class="form-group" style="grid-column: 1 / -1;">
                                <label>PRAC Content to Monitor</label>
                                <div class="checkbox-grid">
                                    ${SOURCE_CONTENT_OPTIONS.map(type => `
                                        <label class="config-check">
                                            <input
                                                type="checkbox"
                                                data-source-field="content_type"
                                                value="${escapeHtml(type)}"
                                                ${selectedContent.has(type) ? "checked" : ""}
                                            >
                                            ${escapeHtml(type)}
                                        </label>
                                    `).join("")}
                                </div>
                            </div>
                        </div>

                        <div class="card-actions">
                            <button class="btn btn-primary" onclick="saveSourceConfiguration(${source.id})">
                                Save
                            </button>
                            <button class="btn btn-secondary" onclick="toggleSourceActive(${source.id}, false)">
                                Deactivate
                            </button>
                        </div>
                    </div>
                `;
            }).join("")}
        </div>
    `;
}

function renderProductConfigurationCards(productClasses) {

    const classes = Array.isArray(productClasses) ? productClasses : [];

    if (!classes.length) {
        return `
            <div class="empty-state">
                <h4>No product classes configured</h4>
            </div>
        `;
    }

    return `
        <div class="config-section-header">
            <div class="card-title">
                Product Configuration
            </div>
            <button
                class="btn btn-primary"
                onclick="addProductClass()"
            >
                + Add Product Class
            </button>
        </div>

        <div class="product-class-stack">
            ${classes.map(productClass => {
                const products = productClass.products || [];

                return `
                    <details class="product-class-card" open>
                        <summary>
                            <div class="product-class-summary">
                                <span>▼</span>
                                <span class="summary-name">${escapeHtml(productClass.class_name || "Product Class")}</span>
                                <span class="summary-count">${products.length} products</span>
                            </div>

                            <div class="inline-button-group">
                                <button class="btn btn-secondary btn-small" type="button" onclick="event.preventDefault(); editProductClass(${productClass.id});">
                                    Edit
                                </button>
                                <button class="btn btn-secondary btn-small" type="button" onclick="event.preventDefault(); addProductToClass(${productClass.id});">
                                    Add Product
                                </button>
                                <button class="btn btn-danger btn-small" type="button" onclick="event.preventDefault(); deactivateProductClass(${productClass.id});">
                                    Delete / Deactivate
                                </button>
                            </div>
                        </summary>

                        <div class="product-list">
                            ${products.map(product => `
                                <div class="product-row">
                                    <span>${escapeHtml(product.product_name || "Product")}</span>
                                    <div class="inline-button-group">
                                        <button class="btn btn-secondary btn-small" type="button" onclick="event.preventDefault(); editProduct(${product.id});">
                                            Edit
                                        </button>
                                        <button class="btn btn-danger btn-small" type="button" onclick="event.preventDefault(); deactivateProduct(${product.id});">
                                            Delete / Deactivate
                                        </button>
                                    </div>
                                </div>
                            `).join("") || '<div class="empty-inline">No products in this class.</div>'}
                        </div>
                    </details>
                `;
            }).join("")}
        </div>
    `;
}

async function loadConfiguration() {

    const [triggers, sources, productClasses] = await Promise.all([
        apiRequest("/triggers"),
        apiRequest("/sources"),
        apiRequest("/product-classes"),
    ]);

    const sourceContainer = $("websiteSourceConfiguration");
    const productContainer = $("productConfiguration");
    const triggerContainer = $("trigger-configuration");

    if (sourceContainer) {
        sourceContainer.innerHTML = renderSourceConfigurationCards(sources);
    }

    if (productContainer) {
        productContainer.innerHTML = renderProductConfigurationCards(productClasses);
    }

    if (!triggerContainer) {
        return;
    }

    triggerContainer.innerHTML = triggers.map(
        trigger => `

            <div
                style="
                    display:flex;
                    flex-direction:column;
                    gap:14px;
                "
            >

                <div class="configuration-item">

                    <span>
                        Trigger Name
                    </span>

                    <strong>
                        ${escapeHtml(
                            trigger.name
                        )}
                    </strong>

                </div>


                <div class="configuration-item">

                    <span>
                        Trigger Type
                    </span>

                    <strong>
                        ${escapeHtml(
                            trigger.type
                        )}
                    </strong>

                </div>


                <div class="configuration-item">

                    <span>
                        Status
                    </span>

                    <strong>
                        Active
                    </strong>

                </div>


                <div class="configuration-item">

                    <span>
                        Active Substances
                    </span>

                    <div
                        style="
                            line-height:1.7;
                            font-size:13px;
                        "
                    >
                        ${(trigger.substances || []).map(
                            substance =>
                                `<span
                                    class="badge badge-neutral"
                                    style="margin:3px;"
                                >
                                    ${escapeHtml(
                                        substance
                                    )}
                                </span>`
                        ).join("")}
                    </div>

                </div>


                <div class="configuration-item">

                    <span>
                        Safety Terms
                    </span>

                    <div
                        style="
                            line-height:1.7;
                            font-size:13px;
                        "
                    >
                        ${(trigger.safety_terms || []).map(
                            term =>
                                `<span
                                    class="badge badge-neutral"
                                    style="margin:3px;"
                                >
                                    ${escapeHtml(
                                        term
                                    )}
                                </span>`
                        ).join("")}
                    </div>

                </div>

            </div>

        `
    ).join("");

    await checkOllamaStatus();
}

async function saveSourceConfiguration(sourceId) {

    const card = document.querySelector(`[data-source-card="${sourceId}"]`);
    if (!card) {
        return;
    }

    const source = {
        reference_no: card.querySelector('[data-source-field="reference_no"]').value.trim(),
        authority: "European Medicines Agency",
        name: card.querySelector('[data-source-field="name"]').value.trim() || "Configured Source",
        source_type: card.querySelector('[data-source-field="source_type"]').value.trim() || "Health Authority",
        region: card.querySelector('[data-source-field="region"]').value.trim() || "EEA",
        monitoring_frequency: card.querySelector('[data-source-field="monitoring_frequency"]').value,
        website: card.querySelector('[data-source-field="website"]').value.trim() || "EMA",
        safety_alert_type: card.querySelector('[data-source-field="safety_alert_type"]').value.trim() || "PRAC",
        url: card.querySelector('[data-source-field="url"]').value.trim(),
        content_types: Array.from(card.querySelectorAll('[data-source-field="content_type"]:checked')).map(item => item.value),
        instruction: card.querySelector('[data-source-field="instruction"]').value,
        active: card.querySelector('[data-source-field="active"]').checked,
    };

    try {
        await apiRequest(`/api/sources/${sourceId}`, {
            method: "PATCH",
            body: JSON.stringify(source),
        });
        showToast("Source configuration saved.", "success");
        await loadConfiguration();
    } catch (error) {
        showToast(error.message || "Unable to save source configuration.", "error");
    }
}

async function toggleSourceActive(sourceId, active) {

    try {
        await apiRequest(`/api/sources/${sourceId}`, {
            method: "PATCH",
            body: JSON.stringify({ active }),
        });
        showToast(active ? "Source activated." : "Source deactivated.", "success");
        await loadConfiguration();
    } catch (error) {
        showToast(error.message || "Unable to update source status.", "error");
    }
}

async function addProductClass() {

    const className = window.prompt("Product class name:");
    if (!className || !className.trim()) {
        return;
    }

    try {
        await apiRequest("/api/product-classes", {
            method: "POST",
            body: JSON.stringify({ class_name: className.trim() }),
        });
        showToast("Product class created.", "success");
        await loadConfiguration();
    } catch (error) {
        showToast(error.message || "Unable to create product class.", "error");
    }
}

async function editProductClass(classId) {

    const className = window.prompt("Update product class name:");
    if (!className || !className.trim()) {
        return;
    }

    try {
        await apiRequest(`/api/product-classes/${classId}`, {
            method: "PATCH",
            body: JSON.stringify({ class_name: className.trim() }),
        });
        showToast("Product class updated.", "success");
        await loadConfiguration();
    } catch (error) {
        showToast(error.message || "Unable to update product class.", "error");
    }
}

async function addProductToClass(classId) {

    const productName = window.prompt("Product name:");
    if (!productName || !productName.trim()) {
        return;
    }

    try {
        await apiRequest("/api/products", {
            method: "POST",
            body: JSON.stringify({
                product_class_id: Number(classId),
                product_name: productName.trim(),
            }),
        });
        showToast("Product added.", "success");
        await loadConfiguration();
    } catch (error) {
        showToast(error.message || "Unable to add product.", "error");
    }
}

async function editProduct(productId) {

    const productName = window.prompt("Update product name:");
    if (!productName || !productName.trim()) {
        return;
    }

    try {
        await apiRequest(`/api/products/${productId}`, {
            method: "PATCH",
            body: JSON.stringify({ product_name: productName.trim() }),
        });
        showToast("Product updated.", "success");
        await loadConfiguration();
    } catch (error) {
        showToast(error.message || "Unable to update product.", "error");
    }
}

async function deactivateProductClass(classId) {

    if (!window.confirm("Deactivate this product class?")) {
        return;
    }

    try {
        await apiRequest(`/api/product-classes/${classId}`, {
            method: "PATCH",
            body: JSON.stringify({ active: false }),
        });
        showToast("Product class deactivated.", "success");
        await loadConfiguration();
    } catch (error) {
        showToast(error.message || "Unable to deactivate product class.", "error");
    }
}

async function deactivateProduct(productId) {

    if (!window.confirm("Deactivate this product?")) {
        return;
    }

    try {
        await apiRequest(`/api/products/${productId}`, {
            method: "PATCH",
            body: JSON.stringify({ active: false }),
        });
        showToast("Product deactivated.", "success");
        await loadConfiguration();
    } catch (error) {
        showToast(error.message || "Unable to deactivate product.", "error");
    }
}


async function checkOllamaStatus() {

    const element =
        $("ollama-status");

    try {

        const result =
            await apiRequest(
                "/ollama/test"
            );

        if (!element) {
            return;
        }

        if (
            result.available &&
            result.model_available
        ) {

            element.textContent =
                `Connected (${result.model || "model"})`;

            element.style.color =
                "#16a34a";

        } else if (
            result.available
        ) {

            element.textContent =
                "Ollama available — model not installed";

            element.style.color =
                "#d97706";

        } else {

            element.textContent =
                "Unavailable";

            element.style.color =
                "#dc2626";
        }

    } catch {

        if (element) {
            element.textContent =
                "Unavailable";
        }
    }
}


async function testOllama() {

    const button =
        $("test-ollama-button");

    const resultBox =
        $("ollama-test-result");

    if (button) {
        button.disabled = true;
        button.textContent =
            "Testing...";
    }

    try {

        const result =
            await apiRequest(
                "/ollama/test"
            );

        if (resultBox) {

            resultBox.innerHTML = `

                <div
                    style="
                        margin-top:12px;
                        padding:12px;
                        border-radius:8px;
                    "
                >

                    <strong>
                        ${
                            result.available
                                ? "Ollama Available"
                                : "Ollama Unavailable"
                        }
                    </strong>

                    <p>
                        ${escapeHtml(
                            result.message ||
                            "Connection checked."
                        )}
                    </p>

                    <small>
                        Model:
                        ${escapeHtml(
                            result.model ||
                            "—"
                        )}
                    </small>

                </div>
            `;
        }

        await checkOllamaStatus();

    } catch (error) {

        if (resultBox) {

            resultBox.innerHTML = `
                <div>
                    ${escapeHtml(
                        error.message
                    )}
                </div>
            `;
        }

    } finally {

        if (button) {

            button.disabled = false;

            button.textContent =
                "Test Local AI Connection";
        }
    }
}


/* ============================================================
   AUDIT HISTORY
   ============================================================ */

async function loadHistory() {

    const data =
        await apiRequest(
            "/history"
        );

    renderHistoryTable(
        $("crawl-history"),
        data.crawl_history || [],
        "crawl"
    );

    renderHistoryTable(
        $("extraction-history"),
        data.extraction_history || [],
        "extraction"
    );

    renderEnhancedAuditHistory(
        data
    );
}


function renderHistoryTable(
    container,
    rows,
    type
) {

    if (!container) {
        return;
    }

    if (!rows.length) {

        container.innerHTML = `
            <div class="empty-state">
                No history recorded yet.
            </div>
        `;

        return;
    }

    if (type === "crawl") {

        container.innerHTML = `

            <table class="data-table">

                <thead>

                    <tr>
                        <th>Started</th>
                        <th>Completed</th>
                        <th>Source</th>
                        <th>PDFs Found</th>
                        <th>Status</th>
                    </tr>

                </thead>

                <tbody>

                    ${rows.map(
                        row => `

                        <tr>

                            <td>
                                ${formatDate(
                                    row.started_at
                                )}
                            </td>

                            <td>
                                ${formatDate(
                                    row.completed_at
                                )}
                            </td>

                            <td>
                                ${escapeHtml(
                                    row.source_name ||
                                    "Source"
                                )}
                            </td>

                            <td>
                                ${
                                    row.documents_found ??
                                    0
                                }
                            </td>

                            <td>
                                ${statusBadge(
                                    row.status
                                )}
                            </td>

                        </tr>

                    `
                    ).join("")}

                </tbody>

            </table>
        `;

        return;
    }


    container.innerHTML = `

        <table class="data-table">

            <thead>

                <tr>
                    <th>Document</th>
                    <th>Started</th>
                    <th>Completed</th>
                    <th>Pages Extracted</th>
                    <th>Status</th>
                </tr>

            </thead>

            <tbody>

                ${rows.map(
                    row => `

                    <tr>

                        <td class="primary-cell">
                            ${escapeHtml(
                                row.document_title ||
                                row.filename ||
                                "Document"
                            )}
                        </td>

                        <td>
                            ${formatDate(
                                row.started_at
                            )}
                        </td>

                        <td>
                            ${formatDate(
                                row.completed_at
                            )}
                        </td>

                        <td>
                            ${
                                row.pages_extracted ??
                                0
                            }
                        </td>

                        <td>
                            ${statusBadge(
                                row.status
                            )}
                        </td>

                    </tr>

                `
                ).join("")}

            </tbody>

        </table>
    `;
}


function renderEnhancedAuditHistory(
    data
) {

    const page =
        $("page-history");

    if (!page) {
        return;
    }

    let container =
        $("enhanced-audit-history");

    if (!container) {

        container =
            document.createElement(
                "div"
            );

        container.id =
            "enhanced-audit-history";

        container.className =
            "panel";

        page.appendChild(
            container
        );
    }

    const detection =
        data.detection_history || [];

    const summaries =
        data.summary_history || [];

    const reviews =
        data.review_history || [];

    const config =
        data.monitoring_config || {};


    container.innerHTML = `

        <div class="panel-header">

            <div>

                <span class="panel-eyebrow">
                    TRACEABILITY
                </span>

                <h3>
                    Complete Monitoring Audit
                </h3>

                <p class="panel-description">
                    Crawler → PDF extraction →
                    detection → comparison →
                    summary → human review.
                </p>

            </div>

        </div>


        <div
            style="
                display:grid;
                grid-template-columns:
                    repeat(auto-fit,minmax(300px,1fr));
                gap:12px;
                margin-top:16px;
            "
        >

            <div class="configuration-item">

                <span>
                    PRAC Section XPath
                </span>

                <strong
                    style="
                        font-family:monospace;
                        font-size:11px;
                        word-break:break-word;
                    "
                >
                    ${escapeHtml(
                        config.section_xpath ||
                        "//h2[normalize-space()='PRAC minutes']"
                    )}
                </strong>

            </div>


            <div class="configuration-item">

                <span>
                    Meeting PDF XPath
                </span>

                <strong
                    style="
                        font-family:monospace;
                        font-size:11px;
                        word-break:break-word;
                    "
                >
                    ${escapeHtml(
                        config.meeting_pdf_xpath ||
                        "//a[contains(@href, '/documents/minutes/minutes-prac-meeting-')]"
                    )}
                </strong>

            </div>

        </div>


        <div style="margin-top:28px;">

            <span class="panel-eyebrow">
                DETECTION & COMPARISON
            </span>

            <h3>
                New Information Assessment
            </h3>


            <div style="overflow-x:auto;">

                <table class="data-table">

                    <thead>

                        <tr>
                            <th>Document</th>
                            <th>Meeting Date</th>
                            <th>Findings</th>
                            <th>New Information</th>
                            <th>Summary PDF</th>
                        </tr>

                    </thead>

                    <tbody>

                        ${
                            detection.length
                                ? detection.map(
                                    row => `

                                    <tr>

                                        <td class="primary-cell">
                                            ${escapeHtml(
                                                row.document_title ||
                                                row.filename ||
                                                "PRAC Minutes"
                                            )}
                                        </td>

                                        <td>
                                            ${escapeHtml(
                                                row.meeting_date ||
                                                "—"
                                            )}
                                        </td>

                                        <td>
                                            ${
                                                row.findings_count ??
                                                0
                                            }
                                        </td>

                                        <td>
                                            ${
                                                Number(
                                                    row.new_information_count
                                                ) > 0

                                                    ? `
                                                        <span
                                                            class="badge badge-warning"
                                                        >
                                                            ${
                                                                row.new_information_count
                                                            }
                                                            NEW
                                                        </span>
                                                    `

                                                    : `
                                                        <span
                                                            class="badge badge-neutral"
                                                        >
                                                            NO NEW INFORMATION
                                                        </span>
                                                    `
                                            }
                                        </td>

                                        <td>

                                            <div
                                                style="
                                                    display:flex;
                                                    gap:6px;
                                                "
                                            >

                                                <a
                                                    class="button button-secondary"
                                                    href="/api/documents/${row.document_id}/summary-pdf"
                                                    target="_blank"
                                                >
                                                    View
                                                </a>

                                                <a
                                                    class="button button-primary"
                                                    href="/api/documents/${row.document_id}/summary-pdf/download"
                                                >
                                                    Download
                                                </a>

                                            </div>

                                        </td>

                                    </tr>

                                `
                                ).join("")
                                : `
                                    <tr>
                                        <td colspan="5">
                                            No detection history yet.
                                        </td>
                                    </tr>
                                `
                        }

                    </tbody>

                </table>

            </div>

        </div>


        <div style="margin-top:28px;">

            <span class="panel-eyebrow">
                OLLAMA
            </span>

            <h3>
                AI Summary History
            </h3>


            <div style="overflow-x:auto;">

                <table class="data-table">

                    <thead>

                        <tr>
                            <th>Document</th>
                            <th>Page</th>
                            <th>Model</th>
                            <th>Status</th>
                            <th>Generated</th>
                        </tr>

                    </thead>

                    <tbody>

                        ${
                            summaries.length
                                ? summaries.map(
                                    row => `

                                    <tr>

                                        <td>
                                            ${escapeHtml(
                                                row.document_title ||
                                                "—"
                                            )}
                                        </td>

                                        <td>
                                            ${
                                                row.page_number ??
                                                "—"
                                            }
                                        </td>

                                        <td>
                                            ${escapeHtml(
                                                row.model ||
                                                "—"
                                            )}
                                        </td>

                                        <td>
                                            ${statusBadge(
                                                row.status
                                            )}
                                        </td>

                                        <td>
                                            ${formatDate(
                                                row.generated_at
                                            )}
                                        </td>

                                    </tr>

                                `
                                ).join("")
                                : `
                                    <tr>
                                        <td colspan="5">
                                            No AI summaries generated.
                                        </td>
                                    </tr>
                                `
                        }

                    </tbody>

                </table>

            </div>

        </div>


        <div style="margin-top:28px;">

            <span class="panel-eyebrow">
                HUMAN REVIEW
            </span>

            <h3>
                Reviewer History
            </h3>


            <div style="overflow-x:auto;">

                <table class="data-table">

                    <thead>

                        <tr>
                            <th>Finding</th>
                            <th>Reviewer</th>
                            <th>Decision</th>
                            <th>Comments</th>
                            <th>Reviewed</th>
                        </tr>

                    </thead>

                    <tbody>

                        ${
                            reviews.length
                                ? reviews.map(
                                    row => `

                                    <tr>

                                        <td>
                                            #${row.finding_id}
                                        </td>

                                        <td>
                                            ${escapeHtml(
                                                row.reviewer ||
                                                "—"
                                            )}
                                        </td>

                                        <td>
                                            ${reviewBadge(
                                                row.decision
                                            )}
                                        </td>

                                        <td>
                                            ${escapeHtml(
                                                row.comments ||
                                                "—"
                                            )}
                                        </td>

                                        <td>
                                            ${formatDate(
                                                row.reviewed_at
                                            )}
                                        </td>

                                    </tr>

                                `
                                ).join("")
                                : `
                                    <tr>
                                        <td colspan="5">
                                            No reviewer decisions yet.
                                        </td>
                                    </tr>
                                `
                        }

                    </tbody>

                </table>

            </div>

        </div>

    `;
}


/* ============================================================
   MONITORING
   ============================================================ */

async function runMonitoring() {

    const buttons =
        document.querySelectorAll(
            "#run-monitoring-button, #quick-run-monitoring"
        );

    buttons.forEach(
        button => {
            button.disabled = true;
        }
    );

    try {

        const result =
            await apiRequest(
                "/monitoring/run",
                {
                    method: "POST"
                }
            );

        monitoringJobId =
            result.job_id;

        showMonitoringBanner(
            true
        );

        showToast(
            "Monitoring started.",
            "info"
        );

        startMonitoringPolling();

    } catch (error) {

        showToast(
            error.message,
            "error"
        );

        buttons.forEach(
            button => {
                button.disabled = false;
            }
        );
    }
}


function startMonitoringPolling() {

    if (monitoringTimer) {
        clearInterval(
            monitoringTimer
        );
    }

    monitoringTimer =
        setInterval(
            checkMonitoringStatus,
            1000
        );
}


async function checkMonitoringStatus() {

    if (!monitoringJobId) {
        return;
    }

    try {

        const job =
            await apiRequest(
                `/monitoring/status/${monitoringJobId}`
            );

        const progress =
            Number(
                job.progress || 0
            );

        if ($("monitoring-progress")) {

            $("monitoring-progress")
                .style.width =
                `${progress}%`;
        }

        if ($("monitoring-percentage")) {

            $("monitoring-percentage")
                .textContent =
                `${progress}%`;
        }

        if ($("monitoring-message")) {

            $("monitoring-message")
                .textContent =
                job.message ||
                "Monitoring in progress...";
        }

        if (
            job.status === "completed" ||
            job.status === "failed"
        ) {

            clearInterval(
                monitoringTimer
            );

            monitoringTimer =
                null;

            showMonitoringBanner(
                false
            );

            document
                .querySelectorAll(
                    "#run-monitoring-button, #quick-run-monitoring"
                )
                .forEach(
                    button => {
                        button.disabled =
                            false;
                    }
                );

            if (
                job.status ===
                "completed"
            ) {

                showToast(
                    `Monitoring completed. ${job.documents_found ?? 0} PRAC PDF(s) discovered.`,
                    "success"
                );

            } else {

                showToast(
                    job.message ||
                    "Monitoring failed.",
                    "error"
                );
            }

            await loadDashboard();

            if (
                $("page-prac-minutes")
                ?.classList.contains(
                    "active"
                )
            ) {
                await loadDocuments();
            }

            if (
                $("page-history")
                ?.classList.contains(
                    "active"
                )
            ) {
                await loadHistory();
            }
        }

    } catch (error) {

        console.error(
            "Monitoring status error:",
            error
        );
    }
}


function showMonitoringBanner(
    visible
) {

    const banner =
        $("monitoring-banner");

    if (!banner) {
        return;
    }

    banner.classList.toggle(
        "hidden",
        !visible
    );
}


/* ============================================================
   STATUS
   ============================================================ */

function statusBadge(
    status
) {

    const value =
        String(
            status || ""
        ).toUpperCase();

    if (
        value === "SUCCESS" ||
        value === "COMPLETED" ||
        value === "EXTRACTED"
    ) {

        return `
            <span class="badge badge-success">
                ${escapeHtml(
                    status
                )}
            </span>
        `;
    }

    if (
        value === "RUNNING" ||
        value === "QUEUED"
    ) {

        return `
            <span class="badge badge-warning">
                ${escapeHtml(
                    status
                )}
            </span>
        `;
    }

    if (
        value === "FAILED" ||
        value === "ERROR"
    ) {

        return `
            <span class="badge badge-danger">
                ${escapeHtml(
                    status
                )}
            </span>
        `;
    }

    return `
        <span class="badge badge-neutral">
            ${escapeHtml(
                status ||
                "—"
            )}
        </span>
    `;
}


/* ============================================================
   EVENT SETUP
   ============================================================ */

function setupNavigation() {

    document
        .querySelectorAll(
            ".nav-item"
        )
        .forEach(
            item => {

                item.addEventListener(
                    "click",
                    () => {

                        navigateTo(
                            item.dataset.page
                        );

                    }
                );
            }
        );


    document
        .querySelectorAll(
            "[data-page-target]"
        )
        .forEach(
            element => {

                element.addEventListener(
                    "click",
                    () => {

                        navigateTo(
                            element.dataset.pageTarget
                        );

                    }
                );
            }
        );


    const mobile =
        $("mobile-menu-button");

    if (mobile) {

        mobile.addEventListener(
            "click",
            () => {

                $("sidebar")
                    ?.classList.toggle(
                        "open"
                    );

            }
        );
    }
}


function setupButtons() {

    $("run-monitoring-button")
        ?.addEventListener(
            "click",
            runMonitoring
        );

    $("quick-run-monitoring")
        ?.addEventListener(
            "click",
            runMonitoring
        );


    $("test-source-button")
        ?.addEventListener(
            "click",
            async () => {

                try {

                    const sources =
                        await apiRequest(
                            "/sources"
                        );

                    if (!sources.length) {

                        showToast(
                            "No source configured.",
                            "error"
                        );

                        return;
                    }

                    await testConfiguredSource(
                        sources[0].url
                    );

                } catch (error) {

                    showToast(
                        error.message,
                        "error"
                    );
                }
            }
        );


    $("test-ollama-button")
        ?.addEventListener(
            "click",
            testOllama
        );


    $("refresh-button")
        ?.addEventListener(
            "click",
            async () => {

                const active =
                    document.querySelector(
                        ".page.active"
                    );

                const pageName =
                    active?.id?.replace(
                        "page-",
                        ""
                    ) ||
                    "dashboard";

                await loadPageData(
                    pageName
                );

                showToast(
                    "Data refreshed.",
                    "success"
                );
            }
        );


    $("document-search")
        ?.addEventListener(
            "input",
            event => {

                filterDocuments(
                    event.target.value
                );
            }
        );


    $("modal-close")
        ?.addEventListener(
            "click",
            closeModal
        );


    $("modal-overlay")
        ?.addEventListener(
            "click",
            event => {

                if (
                    event.target ===
                    $("modal-overlay")
                ) {
                    closeModal();
                }
            }
        );
}


/* ============================================================
   INITIALIZATION
   ============================================================ */

async function initializeApplication() {

    setupNavigation();

    setupButtons();

    await loadDashboard();

    if ($("last-sync-time")) {

        $("last-sync-time")
            .textContent =
            new Date().toLocaleString(
                "en-IN",
                {
                    day: "2-digit",
                    month: "short",
                    year: "numeric",
                    hour: "2-digit",
                    minute: "2-digit"
                }
            );
    }

    console.log(
        "Safety Trigger frontend loaded successfully."
    );
}


document.addEventListener(
    "DOMContentLoaded",
    initializeApplication
);


/* ============================================================
   GLOBAL FUNCTIONS
   ============================================================ */

window.navigateTo =
    navigateTo;

window.openDocument =
    openDocument;

window.openFindingEvidence =
    openFindingEvidence;

window.showReviewModal =
    showReviewModal;

window.submitReview =
    submitReview;

window.closeModal =
    closeModal;

window.previousViewerPage =
    previousViewerPage;

window.nextViewerPage =
    nextViewerPage;

window.testConfiguredSource =
    testConfiguredSource;

window.runMonitoring =
    runMonitoring;

window.filterDocuments =
    filterDocuments;