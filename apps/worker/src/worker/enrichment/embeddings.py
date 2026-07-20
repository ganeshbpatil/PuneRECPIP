"""Embedding generation for semantic search (Module 11 will query against
`ai_summaries.embedding`). Anthropic does not offer a public embeddings
endpoint, so this uses OpenAI's `text-embedding-3-small` — matching the
1536-dimension `Vector` column already fixed in Module 2's schema."""

from typing import Protocol

import openai

EMBEDDING_MODEL = "text-embedding-3-small"


class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class OpenAIEmbeddingProvider:
    def __init__(self, client: openai.AsyncOpenAI, model: str = EMBEDDING_MODEL):
        self._client = client
        self._model = model

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(model=self._model, input=text)
        return response.data[0].embedding
