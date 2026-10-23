import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crawler.crawler import run_crawler
from extraction.pdf_extractor import extract_all_pdfs
from detection.trigger_detector import run_detection
from detection.comparator import run_comparison


def main():

    print()
    print("=" * 80)
    print("             SAFETY TRIGGER MONITORING POC")
    print("=" * 80)

    # ------------------------------------------------------------
    # STEP 1 — CRAWLER
    # ------------------------------------------------------------

    print()
    print("STEP 1/4 : CRAWLING HEALTH AUTHORITY SOURCES")
    print("-" * 80)

    run_crawler()

    # ------------------------------------------------------------
    # STEP 2 — PDF EXTRACTION
    # ------------------------------------------------------------

    print()
    print("STEP 2/4 : EXTRACTING PDF CONTENT")
    print("-" * 80)

    extract_all_pdfs()

    # ------------------------------------------------------------
    # STEP 3 — SAFETY TRIGGER DETECTION
    # ------------------------------------------------------------

    print()
    print("STEP 3/4 : DETECTING SAFETY TRIGGERS")
    print("-" * 80)

    run_detection()

    # ------------------------------------------------------------
    # STEP 4 — DOCUMENT COMPARISON
    # ------------------------------------------------------------

    print()
    print("STEP 4/4 : COMPARING DOCUMENTS")
    print("-" * 80)

    run_comparison()

    # ------------------------------------------------------------
    # COMPLETE
    # ------------------------------------------------------------

    print()
    print("=" * 80)
    print("                 MONITORING COMPLETED")
    print("=" * 80)
    print()
    print("Database:")
    print("  output/safety_trigger.db")
    print()
    print("Downloaded documents:")
    print("  output/pdfs/")
    print()
    print("=" * 80)


if __name__ == "__main__":
    main()