"""AIExtractor implementations. Both are real, complete SDK usage — this repo
has no ANTHROPIC_API_KEY/OPENAI_API_KEY available to exercise them live (see
docs/modules/05-ai-enrichment.md), so they're verified structurally (request
payload construction, response parsing against a stubbed client) rather than
against a live API. EnrichmentService is tested against a FakeAIExtractor
implementing the same Protocol, the same dependency-injection pattern used
for DiscoverySource (Module 3) and BrowserPool consumers (Module 4).
"""

from typing import Protocol

import anthropic
import openai
from corelib.schemas.enrichment import CompanyExtraction

from worker.enrichment.prompts import EXTRACTION_SYSTEM_PROMPT, build_extraction_prompt

_TOOL_NAME = "record_company_extraction"


class AIExtractor(Protocol):
    async def extract(self, company_name_hint: str, content: str) -> CompanyExtraction: ...


class ExtractionFailedError(Exception):
    pass


class ClaudeExtractor:
    """Uses forced tool-use (`tool_choice`) — Anthropic's documented pattern
    for reliably getting back exactly one, schema-shaped JSON object rather
    than free-form text that merely resembles JSON."""

    def __init__(self, client: anthropic.AsyncAnthropic, model: str = "claude-sonnet-5"):
        self._client = client
        self._model = model

    async def extract(self, company_name_hint: str, content: str) -> CompanyExtraction:
        tool = {
            "name": _TOOL_NAME,
            "description": (
                "Record the structured company profile extracted from the crawled content."
            ),
            "input_schema": CompanyExtraction.model_json_schema(),
        }
        prompt = build_extraction_prompt(company_name_hint, content)
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=EXTRACTION_SYSTEM_PROMPT,
            tools=[tool],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == _TOOL_NAME:
                return CompanyExtraction.model_validate(block.input)
        raise ExtractionFailedError("Claude response contained no tool_use block")


class OpenAIExtractor:
    """Uses `chat.completions.parse(response_format=<pydantic model>)` —
    OpenAI's structured-outputs SDK helper, which derives the JSON schema
    from the Pydantic model and parses the response back into an instance of
    it directly, rather than hand-building/validating raw JSON."""

    def __init__(self, client: openai.AsyncOpenAI, model: str = "gpt-4o-mini"):
        self._client = client
        self._model = model

    async def extract(self, company_name_hint: str, content: str) -> CompanyExtraction:
        response = await self._client.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": build_extraction_prompt(company_name_hint, content)},
            ],
            response_format=CompanyExtraction,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ExtractionFailedError("OpenAI structured output parsing returned no result")
        return parsed
