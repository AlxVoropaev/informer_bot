import pytest

from shared.protocol import (
    EmbedReply,
    EmbedRequest,
    ErrorReply,
    IsRelevantReply,
    IsRelevantRequest,
    Op,
    PingReply,
    PingRequest,
    ProtocolError,
    SummarizeReply,
    SummarizeRequest,
    decode_reply,
    decode_request,
    encode_reply,
    encode_request,
)


def test_summarize_request_roundtrip() -> None:
    req = SummarizeRequest.new(text="hello")
    got = decode_request(encode_request(req))
    assert got == req


def test_is_relevant_request_roundtrip() -> None:
    req = IsRelevantRequest.new(text="post", filter_prompt="ai news")
    got = decode_request(encode_request(req))
    assert got == req


def test_embed_request_roundtrip() -> None:
    req = EmbedRequest.new(text="brief", dimensions=512)
    got = decode_request(encode_request(req))
    assert got == req


def test_ping_request_roundtrip() -> None:
    req = PingRequest.new()
    got = decode_request(encode_request(req))
    assert got == req


def test_summarize_reply_roundtrip() -> None:
    reply = SummarizeReply(id="x", text="brief", input_tokens=10, output_tokens=3)
    got = decode_reply(encode_reply(reply), Op.summarize)
    assert got == reply


def test_is_relevant_reply_roundtrip() -> None:
    reply = IsRelevantReply(id="x", relevant=True, input_tokens=8, output_tokens=1)
    got = decode_reply(encode_reply(reply), Op.is_relevant)
    assert got == reply


def test_embed_reply_roundtrip() -> None:
    reply = EmbedReply(
        id="x", vector=[0.1, 0.2, 0.3], tokens=11, model="qwen3-embedding:4b",
    )
    got = decode_reply(encode_reply(reply), Op.embed)
    assert got == reply


def test_embed_reply_decodes_legacy_payload_without_model() -> None:
    legacy = '{"id":"x","ok":true,"vector":[0.1],"tokens":3}'
    got = decode_reply(legacy, Op.embed)
    assert isinstance(got, EmbedReply)
    assert got.model == ""


def test_ping_reply_roundtrip() -> None:
    reply = PingReply(id="x")
    got = decode_reply(encode_reply(reply), Op.ping)
    assert got == reply


def test_error_reply_roundtrip_any_op() -> None:
    err = ErrorReply(id="x", error="boom")
    encoded = encode_reply(err)
    for op in Op:
        assert decode_reply(encoded, op) == err


def test_malformed_json_raises() -> None:
    with pytest.raises(ProtocolError):
        decode_request("{not json")
    with pytest.raises(ProtocolError):
        decode_reply("{not json", Op.ping)


def test_unknown_op_raises() -> None:
    with pytest.raises(ProtocolError):
        decode_request('{"op": "bogus", "id": "x"}')
