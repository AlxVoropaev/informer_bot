from anthropic import AsyncAnthropic

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 256
SYSTEM_PROMPT = (
    "You summarize Telegram channel posts. "
    "Reply with a 1-2 sentence brief in the language of the post. "
    "No preamble, no quotes, no markdown — just the summary."
)


async def summarize(text: str, client: AsyncAnthropic | None = None) -> str:
    client = client or AsyncAnthropic()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    return next(b.text for b in response.content if b.type == "text").strip()
