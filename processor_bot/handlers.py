from openai import AsyncOpenAI

from informer_bot.summarizer import (
    embed_summary,
    is_relevant_ollama,
    summarize_ollama,
)
from shared.protocol import (
    EmbedReply,
    EmbedRequest,
    IsRelevantReply,
    IsRelevantRequest,
    PingReply,
    PingRequest,
    Reply,
    Request,
    SummarizeReply,
    SummarizeRequest,
)


async def handle_request(
    req: Request,
    *,
    client: AsyncOpenAI,
    chat_model: str,
    embedding_model: str,
) -> Reply:
    match req:
        case PingRequest():
            return PingReply(id=req.id)
        case SummarizeRequest():
            result = await summarize_ollama(
                req.text, client=client, model=chat_model,
                system_prompt=req.system_prompt,
            )
            return SummarizeReply(
                id=req.id,
                text=result.text,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
        case IsRelevantRequest():
            check = await is_relevant_ollama(
                req.text, req.filter_prompt, client=client, model=chat_model,
            )
            return IsRelevantReply(
                id=req.id,
                relevant=check.relevant,
                input_tokens=check.input_tokens,
                output_tokens=check.output_tokens,
            )
        case EmbedRequest():
            emb = await embed_summary(
                req.text,
                client=client,
                provider="ollama",
                model=embedding_model,
                dimensions=req.dimensions,
            )
            return EmbedReply(
                id=req.id,
                vector=emb.vector,
                tokens=emb.tokens,
                model=embedding_model,
            )
