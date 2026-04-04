#!/usr/bin/env python3
"""
hermes_reply.py — CLI tool for Hermes to reply to messages and check unread.

Usage:
  python3 hermes_reply.py              # show unread messages
  python3 hermes_reply.py "your reply" # post a reply from Hermes
"""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

MESSAGES_FILE = Path("/home/hermes/messages.json")


def load() -> list[dict]:
    if not MESSAGES_FILE.exists():
        return []
    return json.loads(MESSAGES_FILE.read_text(encoding="utf-8")).get("messages", [])


def save(messages: list[dict]) -> None:
    MESSAGES_FILE.write_text(
        json.dumps({"messages": messages}, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def show_unread() -> int:
    msgs = load()
    unread = [m for m in msgs if m.get("from") == "jonathan" and not m.get("read_by_hermes")]
    if not unread:
        print("(no unread messages)")
        return 0
    print(f"--- {len(unread)} unread message(s) ---")
    for m in unread:
        print(f"\n[{m['timestamp']}] Jonathan:")
        print(m["text"])
    return len(unread)


def mark_all_read() -> None:
    msgs = load()
    changed = False
    for m in msgs:
        if m.get("from") == "jonathan" and not m.get("read_by_hermes"):
            m["read_by_hermes"] = True
            changed = True
    if changed:
        save(msgs)


def post_reply(text: str) -> None:
    msgs = load()
    msgs.append({
        "id": str(uuid.uuid4()),
        "from": "hermes",
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M"),
        "text": text.strip(),
        "read_by_hermes": True,
    })
    # Also mark all Jonathan messages as read
    for m in msgs:
        if m.get("from") == "jonathan":
            m["read_by_hermes"] = True
    save(msgs)
    print("Reply posted.")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        count = show_unread()
        if count > 0:
            mark_all_read()
    else:
        reply_text = " ".join(sys.argv[1:])
        post_reply(reply_text)
        print(f"Posted: {reply_text[:80]}...")
