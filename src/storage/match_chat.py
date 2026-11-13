"""The chat between two introduced people, who has read how far, blocks and reports.

Messages are encrypted under the pair's first user's key, like the pair's check and plan. Nothing
here is read by Omi: the companion and the operator only ever get counts and times.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select

from agent.shared.clock import utc_now

from .database import ENGINE
from .schema import match_blocks, match_chat_reads, match_messages, match_pairs, match_reports
from .utils import _isoformat_utc, _protect_text, _require_user_id, _unprotect_text

MATCH_MESSAGE_CHARS = 2000
PAGE_SIZE = 50
MATCH_REPORT_REASONS = ("uncomfortable", "not_who_they_said", "spam", "other")
_NOTE_CHARS = 1000


def add_match_message(pair_id: str, sender_id: str, text: str, *, client_id: str | None = None) -> dict[str, Any] | None:
    """Save one message; a second send with the same `client_id` returns the first. None: no such pair."""
    owner_id = _require_user_id(sender_id, "match message")
    body = text.strip()[:MATCH_MESSAGE_CHARS]
    with ENGINE.begin() as connection:
        # The row lock orders two sends in one pair, so ids follow the order people saw.
        key_owner = connection.execute(select(match_pairs.c.user_a).where(match_pairs.c.id == pair_id).with_for_update()).scalar()
        if key_owner is None:
            return None
        if client_id:
            existing = connection.execute(
                select(match_messages).where(
                    match_messages.c.pair_id == pair_id, match_messages.c.sender_id == owner_id, match_messages.c.client_id == client_id
                )
            ).mappings().first()
            if existing is not None:
                return _message(existing, key_owner)
        row = connection.execute(
            match_messages.insert()
            .values(pair_id=pair_id, sender_id=owner_id, body=_protect_text(key_owner, body), client_id=client_id or None, created_at=utc_now())
            .returning(match_messages)
        ).mappings().one()
        return _message(row, key_owner)


def list_match_messages(pair_id: str, *, before: int | None = None, after: int | None = None, limit: int = PAGE_SIZE) -> list[dict[str, Any]]:
    """One page, oldest first: the newest `limit` messages, those before an id, or those after one."""
    limit = max(1, min(int(limit), 200))
    with ENGINE.begin() as connection:
        key_owner = connection.execute(select(match_pairs.c.user_a).where(match_pairs.c.id == pair_id)).scalar()
        if key_owner is None:
            return []
        query = select(match_messages).where(match_messages.c.pair_id == pair_id)
        if after is not None:
            rows = connection.execute(query.where(match_messages.c.id > after).order_by(match_messages.c.id.asc()).limit(limit)).mappings().all()
            return [_message(row, key_owner) for row in rows]
        if before is not None:
            query = query.where(match_messages.c.id < before)
        rows = connection.execute(query.order_by(match_messages.c.id.desc()).limit(limit)).mappings().all()
    return [_message(row, key_owner) for row in reversed(rows)]


def mark_match_chat_read(pair_id: str, user_id: str, upto: int | None = None) -> int:
    """Move the user's read mark forward to `upto` (default: the newest message); returns the mark."""
    owner_id = _require_user_id(user_id, "match chat read")
    with ENGINE.begin() as connection:
        newest = int(connection.execute(select(func.max(match_messages.c.id)).where(match_messages.c.pair_id == pair_id)).scalar() or 0)
        mark = newest if upto is None else max(0, min(int(upto), newest))
        current = connection.execute(
            select(match_chat_reads.c.last_read_id).where(match_chat_reads.c.pair_id == pair_id, match_chat_reads.c.user_id == owner_id).with_for_update()
        ).scalar()
        if current is None:
            connection.execute(match_chat_reads.insert().values(pair_id=pair_id, user_id=owner_id, last_read_id=mark, read_at=utc_now()))
            return mark
        if mark > int(current):
            connection.execute(
                match_chat_reads.update()
                .where(match_chat_reads.c.pair_id == pair_id, match_chat_reads.c.user_id == owner_id)
                .values(last_read_id=mark, read_at=utc_now())
            )
            return mark
        return int(current)


def match_chat_summaries(pair_ids: list[str], user_id: str) -> dict[str, dict[str, Any]]:
    """Per pair: how many messages, when the last one came, and how many the user has not read."""
    if not pair_ids:
        return {}
    with ENGINE.begin() as connection:
        totals = connection.execute(
            select(match_messages.c.pair_id, func.count(), func.max(match_messages.c.created_at))
            .where(match_messages.c.pair_id.in_(pair_ids))
            .group_by(match_messages.c.pair_id)
        ).all()
        marks = dict(
            connection.execute(
                select(match_chat_reads.c.pair_id, match_chat_reads.c.last_read_id).where(
                    match_chat_reads.c.pair_id.in_(pair_ids), match_chat_reads.c.user_id == user_id
                )
            ).all()
        )
        theirs = connection.execute(
            select(match_messages.c.pair_id, match_messages.c.id).where(match_messages.c.pair_id.in_(pair_ids), match_messages.c.sender_id != user_id)
        ).all()
    unread: dict[str, int] = {}
    for pair_id, message_id in theirs:
        if int(message_id) > int(marks.get(pair_id) or 0):
            unread[pair_id] = unread.get(pair_id, 0) + 1
    return {
        pair_id: {"messages": int(count), "last_at": _isoformat_utc(last_at) if last_at else None, "unread": unread.get(pair_id, 0)}
        for pair_id, count, last_at in totals
    }


def match_chat_counts(pair_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Per pair, counts and times only, for the operator and the outcome measure: never the words."""
    if not pair_ids:
        return {}
    with ENGINE.begin() as connection:
        rows = connection.execute(
            select(match_messages.c.pair_id, match_messages.c.sender_id, func.count(), func.min(match_messages.c.created_at), func.max(match_messages.c.created_at))
            .where(match_messages.c.pair_id.in_(pair_ids))
            .group_by(match_messages.c.pair_id, match_messages.c.sender_id)
        ).all()
    out: dict[str, dict[str, Any]] = {}
    for pair_id, sender, count, first, last in rows:
        entry = out.setdefault(pair_id, {"messages": 0, "by_user": {}, "first": first, "last": last})
        entry["messages"] += int(count)
        entry["by_user"][sender] = int(count)
        entry["first"], entry["last"] = min(entry["first"], first), max(entry["last"], last)
    return {
        pair_id: {"messages": e["messages"], "by_user": e["by_user"], "first_at": _isoformat_utc(e["first"]), "last_at": _isoformat_utc(e["last"])}
        for pair_id, e in out.items()
    }


def block_match_user(blocker_id: str, blocked_id: str, *, pair_id: str | None = None) -> None:
    owner_id = _require_user_id(blocker_id, "match block")
    with ENGINE.begin() as connection:
        exists = connection.execute(
            select(match_blocks.c.blocker_id).where(match_blocks.c.blocker_id == owner_id, match_blocks.c.blocked_id == blocked_id)
        ).first()
        if exists is None:
            connection.execute(match_blocks.insert().values(blocker_id=owner_id, blocked_id=blocked_id, pair_id=pair_id, created_at=utc_now()))


def match_block_between(user_a: str, user_b: str) -> bool:
    """True when either of the two has blocked the other."""
    return frozenset((user_a, user_b)) in blocked_match_pairs([user_a, user_b])


def blocked_match_pairs(user_ids: list[str] | None = None) -> set[frozenset[str]]:
    """Every blocked pair of people, either direction; narrowed to pairs touching `user_ids` when given."""
    query = select(match_blocks.c.blocker_id, match_blocks.c.blocked_id)
    if user_ids is not None:
        query = query.where(or_(match_blocks.c.blocker_id.in_(user_ids), match_blocks.c.blocked_id.in_(user_ids)))
    with ENGINE.begin() as connection:
        rows = connection.execute(query).all()
    return {frozenset((blocker, blocked)) for blocker, blocked in rows}


def match_users_blocked_by(user_id: str) -> set[str]:
    with ENGINE.begin() as connection:
        rows = connection.execute(select(match_blocks.c.blocked_id).where(match_blocks.c.blocker_id == user_id)).all()
    return {row[0] for row in rows}


def save_match_report(pair_id: str, reporter_id: str, reported_id: str, reason: str, note: str | None = None) -> dict[str, Any]:
    owner_id = _require_user_id(reporter_id, "match report")
    if reason not in MATCH_REPORT_REASONS:
        raise ValueError(f"unknown report reason: {reason}")
    report_id = str(uuid4())
    cleaned = " ".join(str(note or "").split())[:_NOTE_CHARS]
    with ENGINE.begin() as connection:
        connection.execute(
            match_reports.insert().values(
                id=report_id, pair_id=pair_id, reporter_id=owner_id, reported_id=reported_id, reason=reason,
                note=_protect_text(owner_id, cleaned) if cleaned else None, created_at=utc_now(),
            )
        )
        row = connection.execute(select(match_reports).where(match_reports.c.id == report_id)).mappings().one()
    return _report(row)


def list_match_reports(limit: int = 100) -> list[dict[str, Any]]:
    with ENGINE.begin() as connection:
        rows = connection.execute(select(match_reports).order_by(match_reports.c.created_at.desc()).limit(max(1, min(int(limit), 500)))).mappings().all()
    return [_report(row) for row in rows]


def delete_match_chat_for_user(connection, user_id: str, pair_ids: list[str]) -> dict[str, int]:
    """Account deletion: the chats of every pair the user was in, their read marks, blocks and reports."""
    messages = reads = 0
    if pair_ids:
        messages = connection.execute(match_messages.delete().where(match_messages.c.pair_id.in_(pair_ids))).rowcount or 0
        reads = connection.execute(match_chat_reads.delete().where(match_chat_reads.c.pair_id.in_(pair_ids))).rowcount or 0
    blocks = connection.execute(match_blocks.delete().where(or_(match_blocks.c.blocker_id == user_id, match_blocks.c.blocked_id == user_id))).rowcount or 0
    reports = connection.execute(match_reports.delete().where(or_(match_reports.c.reporter_id == user_id, match_reports.c.reported_id == user_id))).rowcount or 0
    return {"match_messages": int(messages), "match_chat_reads": int(reads), "match_blocks": int(blocks), "match_reports": int(reports)}


def _message(row: Any, key_owner: str) -> dict[str, Any]:
    return {
        "id": int(row["id"]), "pair_id": row["pair_id"], "sender_id": row["sender_id"], "text": _unprotect_text(key_owner, row["body"]),
        "client_id": row.get("client_id"), "created_at": _isoformat_utc(row["created_at"]),
    }


def _report(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"], "pair_id": row["pair_id"], "reporter_id": row["reporter_id"], "reported_id": row["reported_id"], "reason": row["reason"],
        "note": _unprotect_text(row["reporter_id"], row["note"]) if row["note"] else None, "created_at": _isoformat_utc(row["created_at"]),
    }


__all__ = [
    "MATCH_MESSAGE_CHARS", "MATCH_REPORT_REASONS", "add_match_message", "block_match_user", "blocked_match_pairs", "delete_match_chat_for_user",
    "list_match_messages", "list_match_reports", "mark_match_chat_read", "match_block_between", "match_chat_counts", "match_chat_summaries",
    "match_users_blocked_by", "save_match_report",
]
