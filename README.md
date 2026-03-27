# Hermes Dashboard

A minimal status page so Jonathan can check in on Hermes without SSH-ing into the Pi.

## What it shows

- **Projects** — active projects in `~/projects/`
- **Plans** — files from `~/plans/`
- **Recent logs** — last 10 session logs from `~/logs/`
- **Wishlist** — `~/wishlist.md`

## Running

```bash
cd ~/projects/dashboard
python3 app.py
```

Runs on `http://127.0.0.1:5000` by default.

## External access (NAT traversal)

The Pi is behind NAT. Use Cloudflare Tunnel for external access:

```bash
# Quick tunnel (temporary URL, good for testing)
cloudflared tunnel --url http://localhost:5000

# Persistent tunnel (requires cloudflared auth setup)
# see: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/
```

**cloudflared is not yet installed** — Jonathan needs to install it:
```bash
# ARM64 binary for Raspberry Pi 4
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 -O /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared
```

## Running as a service

```ini
# /etc/systemd/system/hermes-dashboard.service
[Unit]
Description=Hermes Dashboard
After=network.target

[Service]
User=hermes
WorkingDirectory=/home/hermes/projects/dashboard
ExecStart=/usr/bin/python3 app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now hermes-dashboard
```

## Dependencies

- Python 3.x
- Flask (`pip3 install flask`)
- markdown-it-py (`pip3 install markdown-it-py`)

Both are pre-installed on this Pi.
