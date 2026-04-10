#!/bin/bash
# day-response.sh — triggered by cron to check for messages and respond.
# Runs during daytime hours (08:00-20:00). If Jonathan has left a message,
# starts a short Claude session to read and reply.

set -euo pipefail

LOCK_FILE="/tmp/hermes-day-response.lock"
LAST_RESPONSE_FILE="/tmp/hermes-day-response-last"
MIN_INTERVAL=5400  # minimum 90 minutes between responses

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# Prevent overlapping instances
if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        log "Another instance running (PID $PID), exiting."
        exit 0
    fi
    rm -f "$LOCK_FILE"
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

# Check for unread messages (read-only count — does NOT mark as read)
UNREAD_COUNT=$(python3 -c "
import json, sys
try:
    data = json.loads(open('/home/hermes/messages.json').read())
    count = sum(1 for m in data.get('messages', [])
                if m.get('from') == 'jonathan' and not m.get('read_by_hermes'))
    print(count)
except Exception:
    print(0)
" 2>/dev/null || echo 0)

if [ "$UNREAD_COUNT" -eq 0 ]; then
    log "No unread messages."
    exit 0
fi

log "$UNREAD_COUNT unread message(s) found."

# Check cooldown — don't respond more than once per 90 minutes
if [ -f "$LAST_RESPONSE_FILE" ]; then
    LAST=$(cat "$LAST_RESPONSE_FILE")
    NOW=$(date +%s)
    ELAPSED=$((NOW - LAST))
    if [ "$ELAPSED" -lt "$MIN_INTERVAL" ]; then
        REMAINING=$(( (MIN_INTERVAL - ELAPSED) / 60 ))
        log "Cooldown active — ${REMAINING}m remaining. Skipping."
        exit 0
    fi
fi

# Record time of this response
date +%s > "$LAST_RESPONSE_FILE"

log "Starting Claude response session..."

PROMPT="Jonathan has left you a message on the dashboard message board (https://fiveminwebsite.com/messages).

This is a daytime check-in — not a full night session. You have about 20 minutes.

First, get context by reading ~/plans/ (especially gpio.md and dashboard.md) so you
know the current state of active projects. This prevents you from asking about things
you already know — e.g. which GPIO pins are wired, what services are running, what
the button does.

Then:
1. Run: python3 ~/projects/dashboard/hermes_reply.py
   This shows you the unread messages.

2. Read them carefully.

3. Reply using: python3 ~/projects/dashboard/hermes_reply.py \"your reply\"
   Keep replies conversational and concise — this is a message thread, not an essay.
   If Jonathan asks you to do something requiring extended work, acknowledge it and note
   that you'll pick it up properly at your next night session (02:00 CET).

4. If this is genuinely urgent or you need to tell Jonathan something important,
   you can send him a brief email to jonathan.leber@fairhandeln.at via msmtp.

That's it — no need to write logs or update plans for a daytime check-in."

timeout 1200 sudo -u hermes claude --dangerously-skip-permissions -p "$PROMPT" || true

log "Response session complete."
