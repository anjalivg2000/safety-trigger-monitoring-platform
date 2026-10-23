import json
import os
from typing import Any, Dict, Optional

import requests


OPENAI_BASE_URL = os.getenv(
    "OPENAI_BASE_URL",
    "https://api.openai.com/v1",
).rstrip("/")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TIMEOUT = int(os.getenv("OPENAI_TIMEOUT", "120"))


def openai_provider_status() -> Dict[str, Any]:
    configured = bool(os.getenv("OPENAI_API_KEY", "").strip())
    return {
        "configured": configured,
        "available": configured,
        "model": OPENAI_MODEL,
        "message": (
            "OpenAI API key is configured."
            if configured
            else "Set OPENAI_API_KEY to enable OpenAI summaries."
        ),
    }


def generate_document_summary(
    title: str,
    content: str,
    instruction: Optional[str] = None,
) -> Dict[str, Any]:
    analysis_requirement = (
        f"Follow this configured source instruction as the analysis requirement:\n{instruction}"
        if instruction
        else "Summarize the document's key safety information and topics."
    )
    prompt = f"""
Analyze one regulatory safety document for a pharmacovigilance reviewer.
{analysis_requirement}
Use only the document text below. Do not infer or invent facts. Return JSON
with one string property named "summary".

Document title: {title}

Document text:
{content[:40000]}
""".strip()
    return _generate_json_summary(prompt, ("summary",))


def generate_finding_summary(finding: Dict[str, Any]) -> Dict[str, Any]:
    prompt = f"""
Prepare a concise topic assessment for a pharmacovigilance human reviewer.
Use only the supplied finding, configured exact product/class mapping, and
exact evidence. Do not infer causality, product-class membership, or facts not
stated in the evidence. The assessment may state whether a PI/SmPC update
warrants consideration, but must preserve uncertainty and is not a final
regulatory decision. Return a JSON object with string properties "summary",
"prac_assessment", and "outcome". Use an empty string for fields not
established by the evidence.

Product: {finding.get("product_name") or "Not stated"}
Active substance: {finding.get("active_substance") or "Not stated"}
Configured product/class mapping: {finding.get("product_class_context") or "No exact configured product match"}
Safety topic: {finding.get("safety_topic") or finding.get("trigger_name") or "Not stated"}
Comparison status: {finding.get("comparison_status") or "Not stated"}
Section: {finding.get("section") or "Not stated"}
The summary must be concise. "prac_assessment" must address supported
product/class impact and possible PI/SmPC update consideration. "outcome"
must be a concise proposed outcome for human review.
Exact evidence:
{str(finding.get("evidence") or "")[:20000]}
""".strip()
    return _generate_json_summary(
        prompt,
        ("summary", "prac_assessment", "outcome"),
    )


def _generate_json_summary(
    prompt: str,
    required_fields: tuple[str, ...],
) -> Dict[str, Any]:
    model = OPENAI_MODEL
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {
            "status": "UNAVAILABLE",
            "model": model,
            "error": "OpenAI is not configured. Set OPENAI_API_KEY to enable summaries.",
        }

    try:
        response = requests.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "Return only valid JSON matching the requested schema.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
            },
            timeout=OPENAI_TIMEOUT,
        )
    except requests.Timeout:
        return {
            "status": "ERROR",
            "model": model,
            "error": "The OpenAI request timed out.",
        }
    except requests.RequestException:
        return {
            "status": "UNAVAILABLE",
            "model": model,
            "error": "Unable to connect to the OpenAI API.",
        }

    if not response.ok:
        status = "UNAVAILABLE" if response.status_code in (401, 403) else "ERROR"
        message = (
            "OpenAI rejected the API key. Check OPENAI_API_KEY."
            if response.status_code in (401, 403)
            else "OpenAI rate limit reached. Try again later."
            if response.status_code == 429
            else f"OpenAI request failed (HTTP {response.status_code})."
        )
        return {"status": status, "model": model, "error": message}

    try:
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        summary = json.loads(content)
    except (ValueError, KeyError, IndexError, TypeError):
        return {
            "status": "ERROR",
            "model": model,
            "error": "OpenAI returned an invalid summary response.",
        }

    if not isinstance(summary, dict) or any(
        not isinstance(summary.get(field), str) for field in required_fields
    ):
        return {
            "status": "ERROR",
            "model": model,
            "error": "OpenAI returned a summary with invalid fields.",
        }

    return {
        "status": "SUCCESS",
        "model": model,
        **{field: summary[field].strip() for field in required_fields},
    }
