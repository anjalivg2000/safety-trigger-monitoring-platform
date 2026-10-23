import unittest
from unittest.mock import patch

from lxml import html

from backend.crawler import (
    DEFAULT_SOURCE_CONFIGS,
    classify_content_type,
    deduplicate_documents,
    discover_configured_documents,
    extract_publication_date,
    normalize_content_types,
)
from backend.product_config import DEFAULT_PRODUCT_CLASSES


class DataCrawlingTestCase(unittest.TestCase):
    def test_default_source_configs_are_stable_and_configured(self):
        reference_ids = {source["reference_no"] for source in DEFAULT_SOURCE_CONFIGS}
        self.assertIn("EMA_PRAC_001", reference_ids)
        self.assertIn("EMA_SIGNAL_001", reference_ids)

        prac = next(
            source
            for source in DEFAULT_SOURCE_CONFIGS
            if source["reference_no"] == "EMA_PRAC_001"
        )
        self.assertEqual(prac["region"], "EEA")
        self.assertEqual(prac["monitoring_frequency"], "Monthly")
        self.assertIn("Meeting Minutes", prac["content_types"])
        self.assertIn("Agendas", prac["content_types"])
        self.assertIn("Highlights", prac["content_types"])

    def test_duplicate_documents_are_removed_by_stable_key(self):
        docs = [
            {
                "title": "PRAC Meeting Minutes",
                "url": "https://www.ema.europa.eu/en/documents/minutes/minutes-prac-meeting-8-11-june-2026_en.pdf",
                "document_key": "https://www.ema.europa.eu/en/documents/minutes/minutes-prac-meeting-8-11-june-2026_en.pdf",
                "publication_date": "25-Sep-2026",
                "status": "NEW",
            },
            {
                "title": "PRAC Meeting Minutes",
                "url": "https://www.ema.europa.eu/en/documents/minutes/minutes-prac-meeting-8-11-june-2026_en.pdf",
                "document_key": "https://www.ema.europa.eu/en/documents/minutes/minutes-prac-meeting-8-11-june-2026_en.pdf",
                "publication_date": "25-Sep-2026",
                "status": "ALREADY_CRAWLED",
            },
            {
                "title": "PRAC Agendas",
                "url": "https://www.ema.europa.eu/en/documents/agenda/agenda-prac-meeting-8-11-june-2026_en.pdf",
                "document_key": "https://www.ema.europa.eu/en/documents/agenda/agenda-prac-meeting-8-11-june-2026_en.pdf",
                "publication_date": "26-Sep-2026",
                "status": "NEW",
            },
        ]

        unique = deduplicate_documents(docs)
        self.assertEqual(len(unique), 2)
        self.assertEqual(
            {doc["url"] for doc in unique},
            {
                "https://www.ema.europa.eu/en/documents/minutes/minutes-prac-meeting-8-11-june-2026_en.pdf",
                "https://www.ema.europa.eu/en/documents/agenda/agenda-prac-meeting-8-11-june-2026_en.pdf",
            },
        )

    def test_content_types_are_normalized(self):
        self.assertEqual(
            normalize_content_types(["Meeting Minutes", "Agendas", "Highlights"]),
            ["Meeting Minutes", "Agendas", "Highlights"],
        )
        self.assertEqual(normalize_content_types("Meeting Minutes"), ["Meeting Minutes"])
        self.assertEqual(
            normalize_content_types("['Meeting Minutes', 'Agendas', 'Highlights']"),
            ["Meeting Minutes", "Agendas", "Highlights"],
        )

    def test_publication_date_uses_explicit_published_metadata(self):
        page = html.fromstring(
            """
            <div class="document-card">
                <h3>
                    <a href="/en/news/meeting-highlights">
                        Meeting highlights 31 August - 3 September 2026
                    </a>
                </h3>
                <div>First published: 04/09/2026</div>
            </div>
            """
        )
        link = page.xpath("//a")[0]

        self.assertEqual(
            extract_publication_date(
                link,
                "https://www.ema.europa.eu/en/committees/prac",
                "Highlights",
            ),
            "04 September 2026",
        )

    def test_discovery_does_not_fetch_each_highlights_article(self):
        page_html = """
            <article>
                <h3>
                    <a href="/en/news/meeting-highlights-prac-31-august-2026">
                        Meeting highlights from PRAC
                    </a>
                </h3>
            </article>
        """

        class Response:
            text = page_html

        with patch(
            "backend.crawler.request_with_retries",
            return_value=Response(),
        ) as request:
            documents = discover_configured_documents(
                "https://www.ema.europa.eu/en/committees/prac",
                ["Highlights"],
            )

        request.assert_called_once()
        self.assertEqual(len(documents), 1)
        self.assertIsNone(documents[0]["publication_date"])

    def test_discovery_filters_configured_types_and_keeps_unknown_pdf_group(self):
        page_html = """
            <article>
                <a href="/en/documents/minutes/minutes-prac-meeting-8-11-june-2026_en.pdf">
                    PRAC meeting minutes
                </a>
                <a href="/en/documents/agenda/agenda-prac-meeting-8-11-june-2026_en.pdf">
                    PRAC meeting agenda
                </a>
                <a href="/en/documents/prac/other-published-document.pdf">
                    Published document
                </a>
            </article>
        """

        class Response:
            text = page_html

        with patch(
            "backend.crawler.request_with_retries",
            return_value=Response(),
        ):
            documents = discover_configured_documents(
                "https://www.ema.europa.eu/en/committees/prac",
                ["Meeting Minutes", "Other published documents"],
            )

        self.assertEqual(
            [document["content_type"] for document in documents],
            ["Meeting Minutes", "Other published documents"],
        )

    def test_discovery_classifies_other_pdf_and_work_plan_groups(self):
        self.assertEqual(
            classify_content_type(
                "PRAC work plan",
                "https://example.test/prac-work-plan.pdf",
            ),
            "Work Plan",
        )
        self.assertEqual(
            classify_content_type(
                "Published document",
                "https://example.test/other-document.pdf",
            ),
            "Other published documents",
        )

    def test_discovery_excludes_navigation_and_uses_publication_date(self):
        page_html = """
            <nav>
                <a href="/en/news-events/committee-highlights">
                    Committee highlights
                </a>
            </nav>
            <article>
                <h3>
                    <a href="/en/news/meeting-highlights-prac-31-august-2026">
                        Meeting highlights from PRAC 31 August 2026
                    </a>
                </h3>
                <div>First published: 04/09/2026</div>
            </article>
        """

        class Response:
            text = page_html

        with patch(
            "backend.crawler.request_with_retries",
            return_value=Response(),
        ):
            documents = discover_configured_documents(
                "https://www.ema.europa.eu/en/committees/prac",
                ["Highlights"],
            )

        self.assertEqual(len(documents), 1)
        self.assertEqual(
            documents[0]["publication_date"],
            "04 September 2026",
        )
        self.assertEqual(documents[0]["meeting_date"], None)

    def test_default_product_classes_and_products_are_seeded(self):
        self.assertEqual(len(DEFAULT_PRODUCT_CLASSES), 5)
        class_names = {item["name"] for item in DEFAULT_PRODUCT_CLASSES}
        self.assertIn("Benzodiazepines", class_names)
        self.assertIn("Angiotensin II receptor blockers (ARBs)", class_names)

        product_count = sum(len(item["products"]) for item in DEFAULT_PRODUCT_CLASSES)
        self.assertEqual(product_count, 18 + 14 + 7 + 21 + 8)

        benzodiazepines = next(
            item for item in DEFAULT_PRODUCT_CLASSES if item["name"] == "Benzodiazepines"
        )
        self.assertIn("Alprazolam", benzodiazepines["products"])
        self.assertIn("Diazepam", benzodiazepines["products"])


if __name__ == "__main__":
    unittest.main()
