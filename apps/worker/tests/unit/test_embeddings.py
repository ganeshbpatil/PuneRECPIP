import httpx
import openai
import pytest
from worker.enrichment.embeddings import EMBEDDING_MODEL, OpenAIEmbeddingProvider

pytestmark = pytest.mark.asyncio


async def test_embed_returns_vector_matching_column_dimension():
    fake_vector = [0.1] * 1536

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"object": "embedding", "index": 0, "embedding": fake_vector}],
                "model": EMBEDDING_MODEL,
                "usage": {"prompt_tokens": 5, "total_tokens": 5},
            },
        )

    client = openai.AsyncOpenAI(
        api_key="sk-fake", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    provider = OpenAIEmbeddingProvider(client)

    vector = await provider.embed("Acme Realty is a residential broker in Pune.")

    assert vector == fake_vector
    assert len(vector) == 1536  # must match corelib.models.ai_summary.EMBEDDING_DIM
