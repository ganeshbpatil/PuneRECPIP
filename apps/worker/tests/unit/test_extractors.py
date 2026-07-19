"""ClaudeExtractor/OpenAIExtractor verified structurally: real SDK objects,
real request-building and response-parsing code paths, driven against
httpx.MockTransport rather than a live API — this repo has no
ANTHROPIC_API_KEY/OPENAI_API_KEY to exercise them for real (see
docs/modules/05-ai-enrichment.md). Response payloads below match each
provider's actual documented response shape."""

import json

import anthropic
import httpx
import openai
import pytest
from corelib.schemas.enrichment import CompanyExtraction
from worker.enrichment.extractors import ClaudeExtractor, ExtractionFailedError, OpenAIExtractor

pytestmark = pytest.mark.asyncio

SAMPLE_EXTRACTION = CompanyExtraction(
    company_name="Acme Realty Pune",
    business_category="Broker",
    services=["Residential resale", "Rentals"],
    specializations=[{"specialization": "residential_sales", "confidence": 0.9}],
    residential_vs_commercial_focus="residential",
    sales_vs_leasing_focus="sales",
    areas_served=["Kothrud", "Baner"],
    year_established=2010,
    confidence_score=0.85,
    summary_markdown=(
        "# Acme Realty Pune\nA residential broker serving Kothrud and Baner since 2010."
    ),
)


async def test_claude_extractor_forces_tool_use_and_parses_response():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "msg_123",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "record_company_extraction",
                        "input": SAMPLE_EXTRACTION.model_dump(mode="json"),
                    }
                ],
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        )

    client = anthropic.AsyncAnthropic(
        api_key="sk-fake", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    extractor = ClaudeExtractor(client)

    result = await extractor.extract("Acme Realty Pune", "crawled markdown content here")

    assert result == SAMPLE_EXTRACTION
    assert captured["body"]["tool_choice"] == {"type": "tool", "name": "record_company_extraction"}
    assert captured["body"]["tools"][0]["name"] == "record_company_extraction"
    assert "Acme Realty Pune" in captured["body"]["messages"][0]["content"]


async def test_claude_extractor_raises_if_no_tool_use_block():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "msg_123",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5",
                "content": [{"type": "text", "text": "I couldn't extract this."}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )

    client = anthropic.AsyncAnthropic(
        api_key="sk-fake", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(ExtractionFailedError):
        await ClaudeExtractor(client).extract("Acme Realty Pune", "content")


async def test_openai_extractor_sends_strict_json_schema_and_parses_response():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-123",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": SAMPLE_EXTRACTION.model_dump_json(),
                            "refusal": None,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
        )

    client = openai.AsyncOpenAI(
        api_key="sk-fake", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    extractor = OpenAIExtractor(client)

    result = await extractor.extract("Acme Realty Pune", "crawled markdown content here")

    assert result == SAMPLE_EXTRACTION
    response_format = captured["body"]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True


async def test_openai_extractor_raises_if_parsing_yields_nothing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-123",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "refusal": "cannot comply",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10},
            },
        )

    client = openai.AsyncOpenAI(
        api_key="sk-fake", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(ExtractionFailedError):
        await OpenAIExtractor(client).extract("Acme Realty Pune", "content")
