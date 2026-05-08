import logging
from dataclasses import dataclass

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

log = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIMENSIONS = 512
MAX_TOKENS_CLAUDE = 256
MAX_TOKENS_OLLAMA = 4000
SYSTEM_PROMPT = (
    "You summarize Telegram channel posts. "
    "Reply with a brief of one or two sentences in the language of the post. "
    "No preamble, no quotes, no markdown — just the summary."
)
FILTER_SYSTEM_PROMPT = (
    "You are a relevance classifier. Given a user's interest description and a "
    "Telegram post, decide whether the post is relevant to the user. "
    "Reply with exactly one token: YES or NO. No punctuation, no explanation."
)
FILTER_MAX_TOKENS = 4

# Per-provider chat pricing in USD per 1M tokens (input, output).
CHAT_PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "anthropic": (1.00, 5.00),  # claude-haiku-4-5
    "openai":    (0.0, 0.0),    # not currently a chat option but keep slot
    "ollama":    (0.0, 0.0),
    "remote":    (0.0, 0.0),
    "unknown":   (1.00, 5.00),  # legacy data — assume Anthropic (the old default)
}

# Per-provider embedding pricing in USD per 1M tokens.
EMBEDDING_PRICES_PER_MTOK: dict[str, float] = {
    "openai":  0.02,  # text-embedding-3-small
    "ollama":  0.0,
    "remote":  0.0,
    "unknown": 0.02,
}


@dataclass(frozen=True)
class Summary:
    text: str
    input_tokens: int
    output_tokens: int
    provider: str


@dataclass(frozen=True)
class RelevanceCheck:
    relevant: bool
    input_tokens: int
    output_tokens: int
    provider: str


@dataclass(frozen=True)
class Embedding:
    vector: list[float]
    tokens: int
    provider: str
    model: str


def estimate_cost_usd(provider: str, input_tokens: int, output_tokens: int) -> float:
    p_in, p_out = CHAT_PRICES_PER_MTOK.get(provider, (0.0, 0.0))
    return input_tokens / 1_000_000 * p_in + output_tokens / 1_000_000 * p_out


def estimate_embedding_cost_usd(provider: str, tokens: int) -> float:
    return tokens / 1_000_000 * EMBEDDING_PRICES_PER_MTOK.get(provider, 0.0)


async def summarize(
    text: str,
    client: AsyncAnthropic | None = None,
    *,
    system_prompt: str | None = None,
) -> Summary:
    client = client or AsyncAnthropic()
    log.debug("summarize: sending %d chars to %s", len(text), MODEL)
    response = await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS_CLAUDE,
        system=system_prompt or SYSTEM_PROMPT,
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
        provider="anthropic",
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
        provider="anthropic",
    )


async def embed_summary(
    summary_text: str,
    client: AsyncOpenAI | None = None,
    *,
    provider: str,
    model: str = EMBED_MODEL,
    dimensions: int | None = EMBED_DIMENSIONS,
) -> Embedding:
    client = client or AsyncOpenAI()
    log.debug("embed_summary: %d chars to %s", len(summary_text), model)
    kwargs: dict = {
        "model": model,
        "input": summary_text,
        "encoding_format": "float",
    }
    if dimensions is not None:
        kwargs["dimensions"] = dimensions
    response = await client.embeddings.create(**kwargs)
    vector = list(response.data[0].embedding)
    log.debug(
        "embed_summary: got %d dims (tokens=%d)",
        len(vector), response.usage.total_tokens,
    )
    return Embedding(
        vector=vector,
        tokens=response.usage.total_tokens,
        provider=provider,
        model=model,
    )


async def summarize_ollama(
    text: str, *, client: AsyncOpenAI, model: str, system_prompt: str | None = None,
) -> Summary:
    log.debug("summarize_ollama: sending %d chars to %s", len(text), model)
    response = await client.chat.completions.create(
        model=model,
        max_tokens=MAX_TOKENS_OLLAMA,
        temperature=0,
        messages=[
            {"role": "system", "content": system_prompt or SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        extra_body={"think": False},
    )
    content = response.choices[0].message.content
    usage = response.usage
    prompt_tokens = usage.prompt_tokens if usage is not None else 0
    completion_tokens = usage.completion_tokens if usage is not None else 0
    if content is None:
        log.warning(
            "summarize_ollama: model returned no content (in=%d out=%d)",
            prompt_tokens, completion_tokens,
        )
        return Summary(
            text="",
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            provider="ollama",
        )
    summary = content.strip()
    log.debug(
        "summarize_ollama: got %d chars back (in=%d out=%d)",
        len(summary), prompt_tokens, completion_tokens,
    )
    return Summary(
        text=summary,
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        provider="ollama",
    )


async def is_relevant_ollama(
    post_text: str, filter_prompt: str, *, client: AsyncOpenAI, model: str
) -> RelevanceCheck:
    user_content = (
        f"User's interest description:\n{filter_prompt}\n\n"
        f"Post:\n{post_text}"
    )
    log.debug("is_relevant_ollama: sending %d chars to %s", len(user_content), model)
    response = await client.chat.completions.create(
        model=model,
        max_tokens=FILTER_MAX_TOKENS,
        temperature=0,
        messages=[
            {"role": "system", "content": FILTER_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        extra_body={"think": False},
    )
    content = response.choices[0].message.content
    usage = response.usage
    prompt_tokens = usage.prompt_tokens if usage is not None else 0
    completion_tokens = usage.completion_tokens if usage is not None else 0
    if content is None:
        log.warning(
            "is_relevant_ollama: model returned no content (in=%d out=%d)",
            prompt_tokens, completion_tokens,
        )
        return RelevanceCheck(
            relevant=False,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            provider="ollama",
        )
    answer = content.strip().upper()
    relevant = answer.startswith("YES")
    log.debug(
        "is_relevant_ollama: answer=%r relevant=%s (in=%d out=%d)",
        answer, relevant, prompt_tokens, completion_tokens,
    )
    return RelevanceCheck(
        relevant=relevant,
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        provider="ollama",
    )
