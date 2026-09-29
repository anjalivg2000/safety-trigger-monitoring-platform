import json
import os
import re
import time
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv


load_dotenv()


OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL",
    "http://localhost:11434"
).rstrip("/")

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "llama3.2"
)

OLLAMA_TIMEOUT = int(
    os.getenv(
        "OLLAMA_TIMEOUT",
        "120"
    )
)

OLLAMA_RETRIES = int(
    os.getenv(
        "OLLAMA_RETRIES",
        "2"
    )
)


def _clean_text(value: Any) -> str:
    """
    Convert a value into safe text for prompts.
    """
    if value is None:
        return ""

    return str(value).strip()


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract JSON from an Ollama response.

    Handles:
    - normal JSON
    - JSON inside ```json ... ```
    - extra text around a JSON object
    """

    if not text:
        return None

    text = text.strip()

    # Remove markdown code fences.
    fenced_match = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )

    if fenced_match:
        text = fenced_match.group(1).strip()

    # First attempt: complete response is JSON.
    try:
        parsed = json.loads(text)

        if isinstance(parsed, dict):
            return parsed

    except json.JSONDecodeError:
        pass

    # Second attempt: locate the first JSON object.
    start = text.find("{")
    end = text.rfind("}")

    if start >= 0 and end > start:

        candidate = text[start:end + 1]

        try:
            parsed = json.loads(candidate)

            if isinstance(parsed, dict):
                return parsed

        except json.JSONDecodeError:
            pass

    return None


def test_ollama_connection() -> Dict[str, Any]:
    """
    Test whether the local Ollama server is available
    and whether the configured model exists.
    """

    url = f"{OLLAMA_BASE_URL}/api/tags"

    try:
        response = requests.get(
            url,
            timeout=10
        )

        response.raise_for_status()

        data = response.json()

        models = data.get("models", [])

        model_names = []

        for model in models:
            if isinstance(model, dict):
                name = model.get("name")

                if name:
                    model_names.append(name)

        model_available = False

        for name in model_names:

            if name == OLLAMA_MODEL:
                model_available = True
                break

            # Also support names such as:
            # llama3.2:latest
            if name.startswith(f"{OLLAMA_MODEL}:"):
                model_available = True
                break

        return {
            "available": True,
            "server": OLLAMA_BASE_URL,
            "model": OLLAMA_MODEL,
            "model_available": model_available,
            "models": model_names,
            "message": (
                "Ollama is available and the configured model is ready."
                if model_available
                else
                "Ollama is available, but the configured model is not installed."
            )
        }

    except requests.exceptions.ConnectionError:
        return {
            "available": False,
            "server": OLLAMA_BASE_URL,
            "model": OLLAMA_MODEL,
            "model_available": False,
            "models": [],
            "message": (
                "Ollama is not running or cannot be reached."
            )
        }

    except requests.exceptions.Timeout:
        return {
            "available": False,
            "server": OLLAMA_BASE_URL,
            "model": OLLAMA_MODEL,
            "model_available": False,
            "models": [],
            "message": (
                "Ollama connection timed out."
            )
        }

    except Exception as exc:
        return {
            "available": False,
            "server": OLLAMA_BASE_URL,
            "model": OLLAMA_MODEL,
            "model_available": False,
            "models": [],
            "message": str(exc)
        }


def build_summary_prompt(
    product_name: Optional[str],
    active_substance: Optional[str],
    trigger_name: Optional[str],
    safety_topic: Optional[str],
    relevant_terms: Optional[str],
    evidence: str,
    section: Optional[str] = None,
    comparison_status: Optional[str] = None
) -> str:
    """
    Build a strict evidence-only prompt for Ollama.
    """

    product = _clean_text(product_name) or "Not explicitly identified"
    substance = _clean_text(active_substance) or "Not identified"
    trigger = _clean_text(trigger_name) or "Not specified"
    topic = _clean_text(safety_topic) or "Not specified"
    terms = _clean_text(relevant_terms) or "Not specified"
    section_text = _clean_text(section) or "Not specified"
    comparison = _clean_text(comparison_status) or "Not specified"
    evidence_text = _clean_text(evidence)

    prompt = f"""
You are a safety-information summarization assistant.

Your task is ONLY to summarize the supplied evidence from a pharmacovigilance
document.

IMPORTANT RULES:

1. Use ONLY the information supplied below.
2. Do NOT invent facts.
3. Do NOT add information from your general knowledge.
4. Do NOT infer causality.
5. Do NOT make a medical diagnosis.
6. Do NOT make a regulatory decision.
7. Do NOT recommend an action.
8. Do NOT claim that a product caused an event unless the supplied evidence
   explicitly states that conclusion.
9. Preserve uncertainty when the source is uncertain.
10. If a field is not supported by the evidence, use null or "Not stated".
11. The summary must be concise and suitable for a human safety reviewer.
12. Mention the evidence faithfully.
13. Do not treat the active substance as a product name unless the evidence
    explicitly identifies it as a product.
14. "NEW_INFORMATION" means that the deterministic comparison identified
    information that was not previously stored. Do not independently decide
    whether something is new.
15. Do not decide whether the finding is relevant or requires escalation.
16. Do not make a regulatory recommendation or conclusion.

INPUT INFORMATION:

Product:
{product}

Active substance:
{substance}

Trigger:
{trigger}

Safety topic:
{topic}

Relevant terms:
{terms}

Document section:
{section_text}

Deterministic comparison status:
{comparison}

BEGIN EXACT EVIDENCE
{evidence_text}
END EXACT EVIDENCE

Return ONLY valid JSON, with no Markdown or explanatory text, using exactly
this structure:

{{
  "product_name": null,
  "active_substance": null,
  "safety_topic": null,
  "prac_assessment": null,
  "outcome": null,
  "summary": null
}}

Field instructions:

product_name:
Use the explicitly identified product name if present.
Otherwise use null.

active_substance:
Use the supplied active substance.

safety_topic:
Use the supplied safety topic when supported.

prac_assessment:
Briefly state what the supplied evidence says about the PRAC assessment.
Do not invent an assessment.

outcome:
Briefly state the outcome or conclusion explicitly present in the evidence.
If no outcome is stated, use "Not stated".

summary:
Write a concise evidence-based safety summary.
Do not introduce facts that are not present in the evidence.
"""

    return prompt.strip()


def _call_ollama(prompt: str) -> Dict[str, Any]:
    """
    Send a prompt to Ollama.
    """

    url = f"{OLLAMA_BASE_URL}/api/generate"

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0
        }
    }

    last_error = None

    for attempt in range(OLLAMA_RETRIES + 1):

        try:

            response = requests.post(
                url,
                json=payload,
                timeout=OLLAMA_TIMEOUT
            )

            response.raise_for_status()

            data = response.json()

            response_text = data.get(
                "response",
                ""
            )

            if not response_text:
                raise ValueError(
                    "Ollama returned an empty response."
                )

            parsed = _extract_json(
                response_text
            )

            if parsed is None:
                raise ValueError(
                    "Ollama response was not valid JSON."
                )

            return {
                "status": "SUCCESS",
                "model": data.get(
                    "model",
                    OLLAMA_MODEL
                ),
                "data": parsed,
                "error": None
            }

        except requests.exceptions.ConnectionError as exc:

            last_error = (
                "Ollama is not running or cannot be reached."
            )

        except requests.exceptions.Timeout as exc:

            last_error = (
                "Ollama request timed out."
            )

        except requests.exceptions.HTTPError as exc:

            last_error = (
                f"Ollama HTTP error: {exc}"
            )

        except Exception as exc:

            last_error = str(exc)

        if attempt < OLLAMA_RETRIES:
            time.sleep(1)

    return {
        "status": "ERROR",
        "model": OLLAMA_MODEL,
        "data": None,
        "error": last_error or "Unknown Ollama error."
    }


def generate_summary(
    product_name: Optional[str],
    active_substance: Optional[str],
    trigger_name: Optional[str],
    safety_topic: Optional[str],
    relevant_terms: Optional[str],
    evidence: str,
    section: Optional[str] = None,
    comparison_status: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate an evidence-only safety summary using local Ollama.

    If Ollama is unavailable, this function does NOT create
    a fake or fallback AI summary.
    """

    connection = test_ollama_connection()

    if not connection["available"]:

        return {
            "status": "UNAVAILABLE",
            "model": OLLAMA_MODEL,
            "product_name": product_name,
            "active_substance": active_substance,
            "safety_topic": safety_topic,
            "prac_assessment": None,
            "outcome": None,
            "summary": None,
            "error": connection["message"]
        }

    if not connection["model_available"]:

        return {
            "status": "MODEL_NOT_INSTALLED",
            "model": OLLAMA_MODEL,
            "product_name": product_name,
            "active_substance": active_substance,
            "safety_topic": safety_topic,
            "prac_assessment": None,
            "outcome": None,
            "summary": None,
            "error": (
                f"Configured Ollama model '{OLLAMA_MODEL}' "
                "is not installed."
            )
        }

    prompt = build_summary_prompt(
        product_name=product_name,
        active_substance=active_substance,
        trigger_name=trigger_name,
        safety_topic=safety_topic,
        relevant_terms=relevant_terms,
        evidence=evidence,
        section=section,
        comparison_status=comparison_status
    )

    result = _call_ollama(
        prompt
    )

    if result["status"] != "SUCCESS":

        return {
            "status": "ERROR",
            "model": OLLAMA_MODEL,
            "product_name": product_name,
            "active_substance": active_substance,
            "safety_topic": safety_topic,
            "prac_assessment": None,
            "outcome": None,
            "summary": None,
            "error": result["error"]
        }

    data = result["data"]

    return {
        "status": "SUCCESS",
        "model": result.get(
            "model",
            OLLAMA_MODEL
        ),
        "product_name": (
            data.get("product_name")
            if data.get("product_name")
            else product_name
        ),
        "active_substance": (
            data.get("active_substance")
            if data.get("active_substance")
            else active_substance
        ),
        "safety_topic": (
            data.get("safety_topic")
            if data.get("safety_topic")
            else safety_topic
        ),
        "prac_assessment": data.get(
            "prac_assessment"
        ),
        "outcome": data.get(
            "outcome"
        ),
        "summary": data.get(
            "summary"
        ),
        "error": None
    }


def generate_summary_from_finding(
    finding: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Convenience function for generating a summary directly
    from a finding dictionary.
    """

    return generate_summary(
        product_name=finding.get(
            "product_name"
        ),
        active_substance=finding.get(
            "active_substance"
        ),
        trigger_name=finding.get(
            "trigger_name"
        ),
        safety_topic=finding.get(
            "safety_topic"
        ),
        relevant_terms=finding.get(
            "relevant_terms"
        ),
        evidence=finding.get(
            "evidence",
            ""
        ),
        section=finding.get(
            "section"
        ),
        comparison_status=finding.get(
            "comparison_status"
        )
    )


if __name__ == "__main__":

    result = test_ollama_connection()

    print(
        json.dumps(
            result,
            indent=2
        )
    )