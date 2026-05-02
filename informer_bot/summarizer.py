import logging

from anthropic import AsyncAnthropic

log = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 256
SYSTEM_PROMPT = (
    "You summarize Telegram channel posts. "
    "Reply with a 1-2 sentence brief in the language of the post. "
    "No preamble, no quotes, no markdown — just the summary."
)


async def summarize(text: str, client: AsyncAnthropic | None = None) -> str:
    client = client or AsyncAnthropic()
    log.debug("summarize: sending %d chars to %s", len(text), MODEL)
    response = await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    summary = next(b.text for b in response.content if b.type == "text").strip()
    log.debug("summarize: got %d chars back", len(summary))
    return summary
