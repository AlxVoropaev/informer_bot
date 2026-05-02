import logging
from dataclasses import dataclass

from anthropic import AsyncAnthropic

log = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 256
SYSTEM_PROMPT = (
    "You summarize Telegram channel posts. "
    "Reply with a 1-2 sentence brief in the language of the post. "
    "No preamble, no quotes, no markdown — just the summary."
)

# Pricing for claude-haiku-4-5 (USD per 1M tokens).
PRICE_PER_MTOK_INPUT = 1.00
PRICE_PER_MTOK_OUTPUT = 5.00


@dataclass(frozen=True)
class Summary:
    text: str
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
