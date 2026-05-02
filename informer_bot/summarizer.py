import logging
from dataclasses import dataclass

from anthropic import AsyncAnthropic

log = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"
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


def estimate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens / 1_000_000 * PRICE_PER_MTOK_INPUT
        + output_tokens / 1_000_000 * PRICE_PER_MTOK_OUTPUT
    )


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
