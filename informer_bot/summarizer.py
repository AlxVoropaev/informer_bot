import asyncio
import logging
import time
from dataclasses import dataclass

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

log = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIMENSIONS = 512
LOCAL_EMBED_MODEL_DEFAULT = "intfloat/multilingual-e5-small"
LOCAL_EMBED_DIMENSIONS = 384
MAX_TOKENS = 256
SYSTEM_PROMPT = (
    "You summarize Telegram channel posts. "
    "Reply with a single-sentence brief in the language of the post. "
    "No preamble, no quotes, no markdown — just the summary."
)
FILTER_SYSTEM_PROMPT = (
    "You are a relevance classifier. Given a user's interest description and a "
    "Telegram post, decide whether the post is relevant to the user. "
    "Reply with exactly one token: YES or NO. No punctuation, no explanation."
)
FILTER_MAX_TOKENS = 4

# Pricing for claude-haiku-4-5 (USD per 1M tokens).
PRICE_PER_MTOK_INPUT = 1.00
PRICE_PER_MTOK_OUTPUT = 5.00
# Pricing for text-embedding-3-small (USD per 1M input tokens).
EMBED_PRICE_PER_MTOK = 0.02


@dataclass(frozen=True)
class Summary:
    text: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class RelevanceCheck:
    relevant: bool
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class Embedding:
    vector: list[float]
    tokens: int


def estimate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens / 1_000_000 * PRICE_PER_MTOK_INPUT
        + output_tokens / 1_000_000 * PRICE_PER_MTOK_OUTPUT
    )


def estimate_embedding_cost_usd(tokens: int) -> float:
    return tokens / 1_000_000 * EMBED_PRICE_PER_MTOK


async def summarize(text: str, client: AsyncAnthropic | None = None) -> Summary:
    client = client or AsyncAnthropic()
    log.debug("summarize: sending %d chars to %s", len(text), MODEL)
    response = await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    summary = next(b.text for b in response.content if b.type == "text").strip()
    log.debug(
        "summarize: got %d chars back (in=%d out=%d)",
        len(summary), response.usage.input_tokens, response.usage.output_tokens,
    )
    return Summary(
        text=summary,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


async def is_relevant(
    post_text: str, filter_prompt: str, client: AsyncAnthropic | None = None
) -> RelevanceCheck:
    client = client or AsyncAnthropic()
    user_content = (
        f"User's interest description:\n{filter_prompt}\n\n"
        f"Post:\n{post_text}"
    )
    log.debug("is_relevant: sending %d chars to %s", len(user_content), MODEL)
    response = await client.messages.create(
        model=MODEL,
        max_tokens=FILTER_MAX_TOKENS,
        system=FILTER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    answer = next(b.text for b in response.content if b.type == "text").strip().upper()
    relevant = answer.startswith("YES")
    log.debug(
        "is_relevant: answer=%r relevant=%s (in=%d out=%d)",
        answer, relevant, response.usage.input_tokens, response.usage.output_tokens,
    )
    return RelevanceCheck(
        relevant=relevant,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


async def embed_summary(
    summary_text: str, client: AsyncOpenAI | None = None
) -> Embedding:
    client = client or AsyncOpenAI()
    log.debug("embed_summary: %d chars to %s", len(summary_text), EMBED_MODEL)
    response = await client.embeddings.create(
        model=EMBED_MODEL,
        input=summary_text,
        dimensions=EMBED_DIMENSIONS,
        encoding_format="float",
    )
    vector = list(response.data[0].embedding)
    log.debug(
        "embed_summary: got %d dims (tokens=%d)",
        len(vector), response.usage.total_tokens,
    )
    return Embedding(vector=vector, tokens=response.usage.total_tokens)


class LocalEmbedder:
    """fastembed-based embedder; runs ONNX on CPU, no token cost."""

    def __init__(self, model_name: str = LOCAL_EMBED_MODEL_DEFAULT) -> None:
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._needs_e5_prefix = "e5" in model_name.lower()
        self._maybe_register_default(model_name)
        log.info("local embedder: loading %s", model_name)
        t0 = time.perf_counter()
        self._model = TextEmbedding(model_name=model_name, threads=1)
        log.info(
            "local embedder: loaded %s in %.2fs", model_name, time.perf_counter() - t0
        )

    @staticmethod
    def _maybe_register_default(model_name: str) -> None:
        # fastembed's built-in mirror for the multilingual MiniLM is currently
        # broken; the maintainers recommend add_custom_model with a direct HF
        # source. We pre-register our default e5-small model the same way so
        # users get a reliable download out of the box.
        if model_name != LOCAL_EMBED_MODEL_DEFAULT:
            return
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType

        if any(
            m["model"] == model_name for m in TextEmbedding.list_supported_models()
        ):
            return
        TextEmbedding.add_custom_model(
            model=model_name,
            pooling=PoolingType.MEAN,
            normalization=True,
            sources=ModelSource(hf=model_name),
            dim=LOCAL_EMBED_DIMENSIONS,
            model_file="onnx/model.onnx",
        )

    def _embed_sync(self, text: str) -> list[float]:
        prefixed = f"passage: {text}" if self._needs_e5_prefix else text
        t0 = time.perf_counter()
        vector = next(iter(self._model.embed([prefixed]))).tolist()
        log.info(
            "local embed: %d chars -> %d dims in %.0f ms (model=%s)",
            len(text), len(vector), (time.perf_counter() - t0) * 1000, self.model_name,
        )
        return vector

    async def embed(self, summary_text: str) -> Embedding:
        vector = await asyncio.to_thread(self._embed_sync, summary_text)
        return Embedding(vector=vector, tokens=0)
