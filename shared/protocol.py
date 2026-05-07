import json
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

REQUEST_FILENAME = "request.json"
REPLY_FILENAME = "reply.json"


class ProtocolError(Exception):
    pass


class Op(StrEnum):
    summarize = "summarize"
    is_relevant = "is_relevant"
    embed = "embed"
    ping = "ping"


@dataclass(frozen=True)
class SummarizeRequest:
    id: str
    text: str

    @classmethod
    def new(cls, text: str) -> "SummarizeRequest":
        return cls(id=str(uuid.uuid4()), text=text)


@dataclass(frozen=True)
class IsRelevantRequest:
    id: str
    text: str
    filter_prompt: str

    @classmethod
    def new(cls, text: str, filter_prompt: str) -> "IsRelevantRequest":
        return cls(id=str(uuid.uuid4()), text=text, filter_prompt=filter_prompt)


@dataclass(frozen=True)
class EmbedRequest:
    id: str
    text: str
    dimensions: int

    @classmethod
    def new(cls, text: str, dimensions: int) -> "EmbedRequest":
        return cls(id=str(uuid.uuid4()), text=text, dimensions=dimensions)


@dataclass(frozen=True)
class PingRequest:
    id: str

    @classmethod
    def new(cls) -> "PingRequest":
        return cls(id=str(uuid.uuid4()))


Request = SummarizeRequest | IsRelevantRequest | EmbedRequest | PingRequest


@dataclass(frozen=True)
class SummarizeReply:
    id: str
    text: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class IsRelevantReply:
    id: str
    relevant: bool
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class EmbedReply:
    id: str
    vector: list[float] = field(default_factory=list)
    tokens: int = 0


@dataclass(frozen=True)
class PingReply:
    id: str


@dataclass(frozen=True)
class ErrorReply:
    id: str
    error: str


Reply = SummarizeReply | IsRelevantReply | EmbedReply | PingReply | ErrorReply


def request_op(req: Request) -> Op:
    match req:
        case SummarizeRequest():
            return Op.summarize
        case IsRelevantRequest():
            return Op.is_relevant
        case EmbedRequest():
            return Op.embed
        case PingRequest():
            return Op.ping
        case _:
            raise ProtocolError(f"unknown request type: {type(req).__name__}")


def encode_request(req: Request) -> str:
    op = request_op(req)
    payload = {"op": op.value, **asdict(req)}
    return json.dumps(payload)


def decode_request(s: str) -> Request:
    data = _loads(s)
    op = data.pop("op", None)
    if op is None:
        raise ProtocolError("missing 'op' field")
    try:
        match Op(op):
            case Op.summarize:
                return SummarizeRequest(**data)
            case Op.is_relevant:
                return IsRelevantRequest(**data)
            case Op.embed:
                return EmbedRequest(**data)
            case Op.ping:
                return PingRequest(**data)
    except ValueError as e:
        raise ProtocolError(f"unknown op: {op!r}") from e
    except TypeError as e:
        raise ProtocolError(f"bad fields for op {op!r}: {e}") from e


def encode_reply(reply: Reply) -> str:
    payload: dict[str, Any] = asdict(reply)
    if isinstance(reply, ErrorReply):
        payload = {"id": reply.id, "ok": False, "error": reply.error}
    else:
        payload = {"id": reply.id, "ok": True, **{k: v for k, v in payload.items() if k != "id"}}
    return json.dumps(payload)


def decode_reply(s: str, op: Op) -> Reply:
    data = _loads(s)
    ok = data.pop("ok", None)
    if ok is None:
        raise ProtocolError("missing 'ok' field")
    if not ok:
        try:
            return ErrorReply(**data)
        except TypeError as e:
            raise ProtocolError(f"bad error reply: {e}") from e
    try:
        match op:
            case Op.summarize:
                return SummarizeReply(**data)
            case Op.is_relevant:
                return IsRelevantReply(**data)
            case Op.embed:
                return EmbedReply(**data)
            case Op.ping:
                return PingReply(**data)
    except TypeError as e:
        raise ProtocolError(f"bad fields for op {op!r} reply: {e}") from e


def _loads(s: str) -> dict[str, Any]:
    try:
        data = json.loads(s)
    except json.JSONDecodeError as e:
        raise ProtocolError(f"malformed JSON: {e}") from e
    if not isinstance(data, dict):
        raise ProtocolError(f"expected JSON object, got {type(data).__name__}")
    return data
