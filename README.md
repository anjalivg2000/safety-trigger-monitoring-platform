# AI summaries

Results keeps the existing structured document Summary and its view/download
actions separate from document AI Analysis. Document AI Analysis uses the
stored extracted text and the instruction saved with that document's source.
Finding topic assessments are separate from the document Summary and use the
exact configured product/class mapping where one exists.

The application can use local Ollama or the OpenAI API for user-requested
summaries. OpenAI is preferred when its API key is configured; otherwise the
application uses the configured Ollama model.

Set `OPENAI_API_KEY` in the server environment to enable OpenAI. Optionally set
`OPENAI_MODEL` (defaults to `gpt-4o-mini`), `OPENAI_BASE_URL` (defaults to
`https://api.openai.com/v1`), and `OPENAI_TIMEOUT` (defaults to 120 seconds).
Restart the backend after changing these settings. Extracted document text and
finding evidence are sent to OpenAI when an OpenAI summary is requested.

# Crawl workflow

On Crawl and Monitor, select a source and discover documents to load metadata
only. Discovered documents are grouped by the content types actually found on
the source page. Select a group, then use Crawl All or the per-document Crawl
action. Previously processed documents are reported as already crawled and are
not downloaded again. Discovery does not fetch individual articles or PDFs.

After a document is processed, Results can generate a deterministic,
structured Document Extraction / POC Summary from extracted headings, key
sentences, and stored safety findings. Summary viewing and summary-PDF download
are separate from opening or downloading the original source PDF. This action
does not require Ollama.

# Topic assessments and review

Finding-level topic summaries are automatically processed every other day at
09:00 in the server's local time zone. Scheduled generation uses the configured
local Ollama model only; provider/model unavailability or failed generations
are recorded as run status rather than represented as completed assessments.
Exact configured product-name matches supply product/class context. The
assessment keeps the concise topic summary, product impact/possible PI-SmPC
update assessment, and proposed outcome in separate fields.

Each finding requires an Initial Review followed by a Final Review. The backend
rejects a final review without an initial review and prevents changing or
deleting the initial review after finalization. The Findings page can export
all stored topics and their latest assessments to an Excel workbook, including
the review history. The operational figures shown there (20 publications, 15
related items prioritized, and a 15-minute turnaround) are workflow targets,
not processing caps.

Source monitoring frequency and instructions can be edited in Configuration
or Crawl and Monitor. Manual mode never schedules runs. Automatic source
discovery can be explicitly enabled in Crawl and Monitor for every alternate
day, weekly, or calendar-monthly runs. The setting and run outcomes are recorded
in the existing audit history, and a saved frequency alone does not enable
automation. Scheduled runs discover and register documents but do not download
or process them.