"""Shared prompt text for both AI providers — the instructions are provider-
agnostic; only the schema-enforcement mechanism (Claude tool-use vs OpenAI
structured outputs) differs between extractors.py's two implementations."""

EXTRACTION_SYSTEM_PROMPT = """\
You are analyzing crawled content from a real estate company's website to build a structured
business profile. Only use what the content actually supports — do not invent services,
specializations, locations, or history the pages don't mention. Where the content is ambiguous
or silent on a field, prefer "unclear" / an empty list / null over guessing. Property
specializations must each be individually justified by something in the content; do not include
a specialization just because it's common for real estate companies in general."""


def build_extraction_prompt(company_name_hint: str, content: str) -> str:
    return (
        f"Company (as discovered): {company_name_hint}\n\n"
        f"Crawled website content follows, one page per section:\n\n{content}\n\n"
        "Extract a structured profile for this company from the content above."
    )
