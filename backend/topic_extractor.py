"""
Deterministic extraction of meeting-minute topic headings.

Topics are taken only from numbered section headings in extracted PDF text.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List


SECTION_MARKER = re.compile(
    r"^(?P<number>\d+(?:\.\d+)*)\.\s*(?P<title>.*)$"
)

HEADER_PREFIXES = (
    "pharmacovigilance risk assessment committee",
    "ema/prac/",
    "page ",
)


def _is_header_or_footer(line: str) -> bool:
    normalized = line.lower()
    return normalized.startswith(HEADER_PREFIXES)


def _clean_title(lines: Iterable[str]) -> str:
    return " ".join(
        re.sub(r"\s+", " ", line).strip()
        for line in lines
        if line.strip()
    ).strip()


def extract_meeting_topics(
    pages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Extract distinct level-one and level-two section headings."""

    topics: List[Dict[str, Any]] = []
    seen = set()

    for page in pages:
        page_number = page.get("page_number")
        page_text = str(
            page.get("page_text", page.get("text", "")) or ""
        )

        if not page_number or not page_text.strip():
            continue

        toc_lines = sum(
            1
            for line in page_text.splitlines()
            if re.search(r"\.{3,}\s*\d+\s*$", line.strip())
        )
        if (
            "table of contents" in page_text.lower()
            or toc_lines >= 2
        ):
            continue

        lines = [
            line.strip()
            for line in page_text.splitlines()
            if line.strip()
        ]

        for index, line in enumerate(lines):
            match = SECTION_MARKER.match(line)
            if not match:
                continue

            number = match.group("number")
            if number.count(".") > 1:
                continue

            title_lines = []
            inline_title = match.group("title").strip()
            if inline_title:
                if inline_title[:1].isdigit():
                    continue
                title_lines.append(inline_title)

            next_index = index + 1
            while next_index < len(lines) and len(title_lines) < 3:
                continuation = lines[next_index]
                if SECTION_MARKER.match(continuation):
                    break
                if _is_header_or_footer(continuation):
                    next_index += 1
                    continue
                if continuation.lower() == "none":
                    break
                if not title_lines:
                    title_lines.append(continuation)
                    next_index += 1
                    continue
                if (
                    continuation[:1].islower()
                    or title_lines[-1].endswith("-")
                ):
                    title_lines.append(continuation)
                    next_index += 1
                    continue
                break

            title = _clean_title(title_lines)
            if not title or len(title) < 3 or len(title) > 240:
                continue

            key = title.casefold()
            if key in seen:
                continue

            seen.add(key)
            topics.append(
                {
                    "section_number": f"{number}.",
                    "title": title,
                    "page_number": int(page_number),
                    "source_text": title,
                }
            )

    return topics


def extract_section_summaries(
    pages: List[Dict[str, Any]],
    topics: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """Build concise, extractive summaries for top-level meeting sections."""

    topics = topics if topics is not None else extract_meeting_topics(pages)
    top_level = [
        topic for topic in topics
        if str(topic.get("section_number", "")).count(".") == 1
    ]
    page_map = {
        int(page.get("page_number")): str(
            page.get("page_text", page.get("text", "")) or ""
        )
        for page in pages
        if page.get("page_number")
    }
    page_numbers = sorted(page_map)
    sections: List[Dict[str, Any]] = []

    for index, topic in enumerate(top_level):
        start = int(topic["page_number"])
        next_start = (
            int(top_level[index + 1]["page_number"])
            if index + 1 < len(top_level)
            else (page_numbers[-1] + 1 if page_numbers else start + 1)
        )
        end = max(start, next_start - 1)
        source_pages = [
            number for number in page_numbers
            if start <= number <= end
            and "table of contents" not in page_map[number].lower()
        ]
        sentences: List[str] = []
        seen = set()
        for number in source_pages:
            text = page_map[number]
            text = re.sub(
                r"(?im)^pharmacovigilance risk assessment committee.*$",
                "",
                text,
            )
            text = re.sub(r"(?im)^page\s+\d+.*$", "", text)
            text = re.sub(r"\s+", " ", text).strip()
            for sentence in re.split(r"(?<=[.!?])\s+", text):
                sentence = sentence.strip(" -")
                normalized = sentence.casefold()
                if (
                    len(sentence) < 45
                    or len(sentence) > 420
                    or normalized in seen
                    or re.search(r"\.{3,}\s*\d+", sentence)
                ):
                    continue
                seen.add(normalized)
                sentences.append(sentence)
        selected = sentences[:5]
        sections.append(
            {
                "section_number": topic.get("section_number"),
                "title": topic.get("title"),
                "summary": " ".join(selected[:3]) if selected else (
                    "Source text was insufficient to generate a detailed "
                    "deterministic summary."
                ),
                "source_pages": source_pages,
                "source_page_start": min(source_pages) if source_pages else start,
                "source_page_end": max(source_pages) if source_pages else end,
            }
        )

    return sections
