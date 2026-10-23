import unittest
from unittest.mock import Mock, patch

from backend.openai_client import (
    generate_document_summary,
    generate_finding_summary,
    openai_provider_status,
)


class OpenAIClientTestCase(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    def test_provider_is_unavailable_without_api_key(self):
        self.assertFalse(openai_provider_status()["available"])
        result = generate_document_summary("Title", "Source text")
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertIn("OPENAI_API_KEY", result["error"])

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    @patch("backend.openai_client.requests.post")
    def test_document_summary_uses_openai_json_response(self, post):
        response = Mock()
        response.ok = True
        response.json.return_value = {
            "choices": [{"message": {"content": '{"summary":"Evidence-based summary."}'}}]
        }
        post.return_value = response

        result = generate_document_summary("Title", "Source text")

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["summary"], "Evidence-based summary.")
        self.assertEqual(result["model"], "gpt-4o-mini")
        self.assertIn("Source text", post.call_args.kwargs["json"]["messages"][1]["content"])

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    @patch("backend.openai_client.requests.post")
    def test_finding_summary_requires_all_evidence_fields(self, post):
        response = Mock()
        response.ok = True
        response.json.return_value = {
            "choices": [{
                "message": {
                    "content": (
                        '{"summary":"Summary.","prac_assessment":"Assessment.",'
                        '"outcome":"Outcome."}'
                    )
                }
            }]
        }
        post.return_value = response

        result = generate_finding_summary({"evidence": "Exact finding evidence"})

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["prac_assessment"], "Assessment.")
        self.assertEqual(result["outcome"], "Outcome.")


if __name__ == "__main__":
    unittest.main()
