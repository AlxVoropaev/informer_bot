import logging
import math
import time
from dataclasses import dataclass

from informer_bot.db import Database

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DuplicateMatch:
    channel_id: int
    message_id: int
    bot_message_id: int
    is_photo: bool
    dup_links: list[tuple[str, str]]
    link: str
    score: float


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} vs {len(b)}")
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def find_duplicate(
    *,
    db: Database,
    user_id: int,
    vec: list[float],
    threshold: float,
    window_seconds: int,
    now: int | None = None,
) -> DuplicateMatch | None:
    cutoff = (int(time.time()) if now is None else now) - window_seconds
    candidates = db.list_dedup_candidates(user_id=user_id, since=cutoff)
    best: DuplicateMatch | None = None
    for cid, mid, bmid, is_photo, dup_links, cand_vec, link in candidates:
        score = cosine(vec, cand_vec)
        if score < threshold:
            continue
        if best is None or score > best.score:
            best = DuplicateMatch(
                channel_id=cid,
                message_id=mid,
                bot_message_id=bmid,
                is_photo=is_photo,
                dup_links=dup_links,
                link=link,
                score=score,
            )
    if best is not None:
        log.info(
            "dedup: duplicate found user=%s -> %s/%s similarity=%.3f",
            user_id, best.channel_id, best.message_id, best.score,
        )
    return best
