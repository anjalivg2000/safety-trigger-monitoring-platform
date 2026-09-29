"""
PDF Processor

Extracts PRAC meeting-minute PDF content page by page
using PyMuPDF.

Responsibilities:
- Open PDF safely
- Extract text page by page
- Return page numbers and text
- Read PDF metadata
- Calculate PDF SHA256
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz


logger = logging.getLogger(
    "safety_trigger_poc.pdf_processor"
)


# ============================================================
# PDF PROCESSOR
# ============================================================

class PDFProcessor:
    """Process PDF files using PyMuPDF."""

    def __init__(
        self,
        pdf_path: str,
    ) -> None:

        self.pdf_path = Path(
            pdf_path
        )

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    def validate(self) -> None:
        """Validate that the PDF exists and is readable."""

        if not self.pdf_path.exists():

            raise FileNotFoundError(
                f"PDF not found: "
                f"{self.pdf_path}"
            )

        if not self.pdf_path.is_file():

            raise ValueError(
                f"Path is not a file: "
                f"{self.pdf_path}"
            )

        if self.pdf_path.stat().st_size == 0:

            raise ValueError(
                "PDF file is empty."
            )

    # --------------------------------------------------------
    # METADATA
    # --------------------------------------------------------

    def metadata(self) -> Dict[str, Any]:
        """Return PDF metadata."""

        self.validate()

        document = None

        try:

            document = fitz.open(
                str(self.pdf_path)
            )

            metadata = (
                document.metadata
                or {}
            )

            return {
                "filename": self.pdf_path.name,
                "page_count": document.page_count,
                "title": metadata.get(
                    "title"
                ),
                "author": metadata.get(
                    "author"
                ),
                "subject": metadata.get(
                    "subject"
                ),
                "keywords": metadata.get(
                    "keywords"
                ),
                "creator": metadata.get(
                    "creator"
                ),
                "producer": metadata.get(
                    "producer"
                ),
            }

        finally:

            if document is not None:

                document.close()

    # --------------------------------------------------------
    # PAGE TEXT
    # --------------------------------------------------------

    def get_page_text(
        self,
        page_number: int,
    ) -> str:
        """
        Extract text from one page.

        page_number is 1-based.
        """

        self.validate()

        if page_number < 1:

            raise ValueError(
                "Page number must be >= 1."
            )

        document = None

        try:

            document = fitz.open(
                str(self.pdf_path)
            )

            if page_number > document.page_count:

                raise IndexError(
                    f"Page {page_number} "
                    f"does not exist. "
                    f"PDF contains "
                    f"{document.page_count} pages."
                )

            page = document.load_page(
                page_number - 1
            )

            return page.get_text(
                "text"
            ).strip()

        finally:

            if document is not None:

                document.close()

    # --------------------------------------------------------
    # ALL PAGES
    # --------------------------------------------------------

    def extract_pages(
        self,
    ) -> List[Dict[str, Any]]:
        """Extract text from every page."""

        self.validate()

        document = None

        pages: List[Dict[str, Any]] = []

        try:

            document = fitz.open(
                str(self.pdf_path)
            )

            for index in range(
                document.page_count
            ):

                page = document.load_page(
                    index
                )

                text = page.get_text(
                    "text"
                ).strip()

                pages.append(
                    {
                        "page_number": index + 1,
                        "text": text,
                    }
                )

            return pages

        finally:

            if document is not None:

                document.close()

    # --------------------------------------------------------
    # SHA256
    # --------------------------------------------------------

    def sha256(self) -> str:
        """Calculate SHA256 hash of the PDF."""

        self.validate()

        digest = hashlib.sha256()

        with self.pdf_path.open(
            "rb"
        ) as file:

            while True:

                chunk = file.read(
                    1024 * 1024
                )

                if not chunk:
                    break

                digest.update(
                    chunk
                )

        return digest.hexdigest()

    # --------------------------------------------------------
    # PROCESS
    # --------------------------------------------------------

    def process(self) -> Dict[str, Any]:
        """Extract complete PDF information."""

        metadata = self.metadata()

        pages = self.extract_pages()

        return {
            "success": True,
            "filename": self.pdf_path.name,
            "sha256": self.sha256(),
            "metadata": metadata,
            "pages": pages,
            "page_count": len(pages),
        }


# ============================================================
# PUBLIC FUNCTIONS
# ============================================================

def process_pdf(
    pdf_path: str,
) -> Dict[str, Any]:
    """Process a PDF and return extracted information."""

    processor = PDFProcessor(
        pdf_path
    )

    return processor.process()


def process_pdf_safe(
    pdf_path: str,
) -> Dict[str, Any]:
    """
    Process a PDF safely.

    Errors are returned as structured data instead
    of being raised to the API layer.
    """

    try:

        return process_pdf(
            pdf_path
        )

    except Exception as exc:

        logger.exception(
            "PDF processing failed: %s",
            pdf_path,
        )

        return {
            "success": False,
            "filename": Path(
                pdf_path
            ).name,
            "pages": [],
            "page_count": 0,
            "error": str(exc),
        }


def get_pdf_metadata(
    pdf_path: str,
) -> Dict[str, Any]:
    """
    Public helper used by the FastAPI API.

    Returns metadata for a PDF.
    """

    processor = PDFProcessor(
        pdf_path
    )

    return processor.metadata()


def get_page_text(
    pdf_path: str,
    page_number: int,
) -> str:
    """Public helper for extracting one page."""

    processor = PDFProcessor(
        pdf_path
    )

    return processor.get_page_text(
        page_number
    )


def calculate_pdf_sha256(
    pdf_path: str,
) -> str:
    """Public helper for PDF SHA256."""

    processor = PDFProcessor(
        pdf_path
    )

    return processor.sha256()


# ============================================================
# COMMAND-LINE TEST
# ============================================================

if __name__ == "__main__":

    import sys

    if len(sys.argv) < 2:

        print(
            "Usage:"
        )

        print(
            "python backend\\pdf_processor.py "
            "<pdf_path>"
        )

        raise SystemExit(1)

    pdf_path = sys.argv[1]

    result = process_pdf_safe(
        pdf_path
    )

    print(
        f"Success: "
        f"{result.get('success')}"
    )

    print(
        f"Pages: "
        f"{result.get('page_count', 0)}"
    )

    print(
        f"SHA256: "
        f"{result.get('sha256')}"
    )

    if result.get("error"):

        print(
            f"Error: "
            f"{result['error']}"
        )