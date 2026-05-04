#!/bin/bash
# day-response.sh — reactive daytime check-in for Hermes
# Triggers when Jonathan posts on the message board OR sends an email.
# Runs every 15 minutes via cron (08:00–22:00).
# Cooldown: at most one response per 90 minutes.

set -euo pipefail

LOCK_FILE="/tmp/hermes-day-response.lock"
LAST_RESPONSE_FILE="/tmp/hermes-day-response-last"
PROCESSED_IDS_FILE="/home/hermes/.hermes-processed-email-ids"
MIN_INTERVAL=5400  # 90 minutes between responses
JONATHAN_EMAIL="jonathan.leber@fairhandeln.at"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# Skip during night session hours (01:45–04:45 CET) — don't interrupt work time
HOUR=$(date +%-H)
MIN=$(date +%-M)
HOURMIN=$((HOUR * 60 + MIN))
if [ "$HOURMIN" -ge 105 ] && [ "$HOURMIN" -le 285 ]; then
    log "Night session hours (01:45–04:45) — skipping."
    exit 0
fi

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

# Sync email
mbsync inbox >> /home/hermes/logs/mbsync.log 2>&1 || log "mbsync warning (non-fatal)"

# --- Check message board for unread messages from Jonathan ---
BOARD_UNREAD=$(python3 -c "
import json
try:
    data = json.loads(open('/home/hermes/messages.json').read())
    count = sum(1 for m in data.get('messages', [])
                if m.get('from') == 'jonathan' and not m.get('read_by_hermes'))
    print(count)
except Exception:
    print(0)
" 2>/dev/null || echo 0)

# --- Check inbox for new emails from Jonathan ---
NEW_EMAIL_IDS=$(python3 << 'PYEOF'
import os, json

INBOX = '/home/hermes/mail/Inbox/new'
PROCESSED_FILE = '/home/hermes/.hermes-processed-email-ids'
JONATHAN = 'jonathan.leber@fairhandeln.at'

try:
    processed = set(open(PROCESSED_FILE).read().strip().split('\n')) if os.path.exists(PROCESSED_FILE) else set()
except Exception:
    processed = set()

new_ids = []
for fname in sorted(os.listdir(INBOX)):
    fpath = os.path.join(INBOX, fname)
    try:
        with open(fpath, 'r', errors='ignore') as f:
            header = f.read(3000)
        if JONATHAN not in header:
            continue
        # Always use filename as ID — reliable across runs and enables post-session file move
        if fname not in processed:
            new_ids.append(fname)
    except Exception:
        pass

print('\n'.join(new_ids))
PYEOF
)

NEW_EMAIL_COUNT=$(echo "$NEW_EMAIL_IDS" | grep -c '[^[:space:]]' || echo 0)

# --- Check for unresponded button presses (within last 4 hours) ---
BUTTON_PRESSES=$(python3 -c "
import json, datetime
try:
    data = json.loads(open('/home/hermes/.button_presses.json').read())
    now = datetime.datetime.now()
    cutoff = now - datetime.timedelta(hours=4)
    recent = [p for p in data
              if not p.get('responded')
              and datetime.datetime.fromisoformat(p['timestamp']) > cutoff]
    print(len(recent))
except Exception:
    print(0)
" 2>/dev/null || echo 0)

if [ "$BOARD_UNREAD" -eq 0 ] && [ "$NEW_EMAIL_COUNT" -eq 0 ] && [ "$BUTTON_PRESSES" -eq 0 ]; then
    log "Nothing new from Jonathan."
    exit 0
fi

log "Triggers: board_unread=$BOARD_UNREAD, new_email=$NEW_EMAIL_COUNT, button_presses=$BUTTON_PRESSES"

# --- Cooldown check ---
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

# Mark this batch of emails as processed (before triggering, to prevent re-triggering on next poll)
if [ -n "$NEW_EMAIL_IDS" ] && [ "$NEW_EMAIL_COUNT" -gt 0 ]; then
    echo "$NEW_EMAIL_IDS" >> "$PROCESSED_IDS_FILE"
    log "Marked $NEW_EMAIL_COUNT email ID(s) as processed."
fi

date +%s > "$LAST_RESPONSE_FILE"
log "Starting response session..."

# Build context block for email — embed content inline so subsequent sessions can't re-discover it
EMAIL_CONTEXT=""
if [ "$NEW_EMAIL_IDS" != "" ] && [ "$NEW_EMAIL_COUNT" -gt 0 ]; then
    EMAIL_BODIES=""
    while IFS= read -r fname; do
        [ -z "$fname" ] && continue
        FPATH="$HOME/mail/Inbox/new/$fname"
        [ -f "$FPATH" ] || continue
        SUBJ=$(python3 -c "
import email, sys
with open('$FPATH', 'r', errors='ignore') as f:
    m = email.message_from_file(f)
print(m.get('Subject','(no subject)'))
" 2>/dev/null || echo "(unknown subject)")
        BODY=$(python3 -c "
import email, sys
with open('$FPATH', 'r', errors='ignore') as f:
    m = email.message_from_file(f)
if m.is_multipart():
    for part in m.walk():
        if part.get_content_type() == 'text/plain':
            b = part.get_payload(decode=True)
            if b:
                print(b.decode('utf-8', errors='ignore')[:2000])
            break
else:
    b = m.get_payload(decode=True)
    if b:
        print(b.decode('utf-8', errors='ignore')[:2000])
" 2>/dev/null || echo "(could not read body)")
        EMAIL_BODIES="${EMAIL_BODIES}
--- Email: ${SUBJ} ---
${BODY}
"
    done <<< "$NEW_EMAIL_IDS"
    EMAIL_CONTEXT="EMAIL: Jonathan sent you $NEW_EMAIL_COUNT new email(s). Here is the content:
${EMAIL_BODIES}
Reply via msmtp to $JONATHAN_EMAIL."
fi

BOARD_CONTEXT=""
if [ "$BOARD_UNREAD" -gt 0 ]; then
    BOARD_CONTEXT="MESSAGE BOARD: $BOARD_UNREAD unread message(s) from Jonathan on https://fiveminwebsite.com/messages. Read them with: python3 ~/projects/dashboard/hermes_reply.py — then reply with: python3 ~/projects/dashboard/hermes_reply.py \"your reply\""
fi

BUTTON_CONTEXT=""
if [ "$BUTTON_PRESSES" -gt 0 ]; then
    BUTTON_CONTEXT="BUTTON: Jonathan pressed the physical button $BUTTON_PRESSES time(s) in the last 4 hours (unresponded). Reply on the message board acknowledging the press. If it's morning, treat it as a greeting. After responding, mark as responded: python3 -c \"import json; d=json.load(open('/home/hermes/.button_presses.json')); [p.update({'responded':True}) for p in d if not p.get('responded')]; open('/home/hermes/.button_presses.json','w').write(json.dumps(d,indent=2))\""
fi

PROMPT="Jonathan has reached out — this is a reactive daytime response. You have about 20 minutes.

$EMAIL_CONTEXT
$BOARD_CONTEXT
$BUTTON_CONTEXT

Quick context: read your most recent log in ~/logs/ (ls ~/logs/*.md | sort | tail -1) if you need to orient yourself — but keep it brief. Today is $(date '+%Y-%m-%d').

Guidelines:
- Keep replies conversational and brief
- If Jonathan asks for extended work, acknowledge it and say you'll handle it tonight at 02:00 CET
- You can respond via email AND/OR message board depending on how Jonathan reached out
- IMPORTANT: Only send email to jonathan.leber@fairhandeln.at if EMAIL_CONTEXT above is non-empty (Jonathan actually emailed you this session). Do NOT send email when triggered only by a button press or message board post — use the message board to reply in those cases.
- No need to write session logs for a daytime check-in
- Don't start any long-running tasks"

timeout 1200 sudo -u hermes claude --dangerously-skip-permissions -p "$PROMPT" || true

# Move processed email files from new/ to cur/ so subsequent sessions can't re-discover them
if [ -n "$NEW_EMAIL_IDS" ] && [ "$NEW_EMAIL_COUNT" -gt 0 ]; then
    while IFS= read -r fname; do
        [ -z "$fname" ] && continue
        SRC="$HOME/mail/Inbox/new/$fname"
        [ -f "$SRC" ] || continue
        # Strip trailing comma, append Seen flag per Maildir convention
        BASENAME="${fname%,}"
        mv "$SRC" "$HOME/mail/Inbox/cur/${BASENAME},S" 2>/dev/null \
            && log "Moved $fname to cur/" \
            || log "Warning: could not move $fname to cur/"
    done <<< "$NEW_EMAIL_IDS"
fi

log "Response session complete."
