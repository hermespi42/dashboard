#!/bin/bash
# healthcheck.sh — verify the dashboard is responding, email if not.
# Designed to run from cron every 30 minutes.

DASHBOARD_URL="http://localhost:5000"
LOG_FILE="/home/hermes/logs/healthcheck.log"
LAST_ALERT_FILE="/tmp/dashboard_alert_sent"

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }

# Check if dashboard responds (5 second timeout)
if curl -sf --max-time 5 "$DASHBOARD_URL" > /dev/null 2>&1; then
    # Dashboard is up. If we had sent an alert, note recovery.
    if [ -f "$LAST_ALERT_FILE" ]; then
        echo "$(timestamp) RECOVERED — dashboard responding again" >> "$LOG_FILE"
        echo "Subject: Hermes dashboard recovered
From: hermes.pi.42@gmail.com
To: jonathan.leber@fairhandeln.at

Dashboard at $DASHBOARD_URL is responding again.
" | msmtp jonathan.leber@fairhandeln.at
        rm -f "$LAST_ALERT_FILE"
    fi
    exit 0
fi

# Dashboard is NOT responding.
echo "$(timestamp) FAIL — dashboard not responding at $DASHBOARD_URL" >> "$LOG_FILE"

# Don't spam — only send one alert per outage (until recovery)
if [ -f "$LAST_ALERT_FILE" ]; then
    exit 1
fi

# Send alert
touch "$LAST_ALERT_FILE"
echo "Subject: Hermes dashboard is down
From: hermes.pi.42@gmail.com
To: jonathan.leber@fairhandeln.at

Dashboard at $DASHBOARD_URL is not responding.
Checked at: $(timestamp)

To check: systemctl status hermes-dashboard
To restart: sudo systemctl restart hermes-dashboard
" | msmtp jonathan.leber@fairhandeln.at

echo "$(timestamp) Alert email sent" >> "$LOG_FILE"
exit 1
