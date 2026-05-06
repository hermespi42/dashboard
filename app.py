"""
Hermes Dashboard — status page for Jonathan.
Shows wishlist, plans, logs, and current project status.
"""

import json
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
import re
from flask import Flask, render_template, abort, jsonify, request, redirect
from markdown_it import MarkdownIt
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

app = Flask(__name__)
HOME = Path("/home/hermes")
MESSAGES_FILE = HOME / "messages.json"
md = MarkdownIt()


def render_md(text: str) -> str:
    return md.render(text)


def read_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError):
        return None


def git_info(repo_path: Path) -> dict | None:
    """Return last commit summary and remote URL for a git repo, or None."""
    try:
        log = subprocess.run(
            ["git", "log", "-1", "--format=%h %s (%cr)", "--"],
            cwd=repo_path, capture_output=True, text=True, timeout=5
        )
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_path, capture_output=True, text=True, timeout=5
        )
        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=repo_path, capture_output=True, text=True, timeout=5
        )
        if log.returncode != 0:
            return None
        return {
            "last_commit": log.stdout.strip() or None,
            "remote": remote.stdout.strip() or None,
            "dirty": bool(status.stdout.strip()),
        }
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def get_logs() -> list[dict]:
    logs = []
    for p in sorted(HOME.glob("logs/*.md"), reverse=True)[:10]:
        content = read_file(p)
        if content:
            logs.append({"name": p.stem, "html": render_md(content)})
    return logs


def get_plans() -> list[dict]:
    plans = []
    for p in sorted(HOME.glob("plans/*.md")):
        content = read_file(p)
        if content:
            plans.append({"name": p.stem, "html": render_md(content)})
    return plans


def get_wishlist() -> str | None:
    content = read_file(HOME / "wishlist.md")
    return render_md(content) if content else None


def get_sysinfo() -> dict | None:
    if not PSUTIL_AVAILABLE:
        return None
    cpu = psutil.cpu_percent(interval=0.2)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    temp = None
    try:
        temps = psutil.sensors_temperatures()
        for key in ("cpu_thermal", "coretemp", "k10temp"):
            if key in temps and temps[key]:
                temp = round(temps[key][0].current, 1)
                break
    except (AttributeError, KeyError):
        pass
    uptime_secs = int(datetime.now().timestamp() - psutil.boot_time())
    hours, rem = divmod(uptime_secs, 3600)
    minutes = rem // 60
    return {
        "cpu_pct": cpu,
        "mem_pct": round(mem.percent, 1),
        "mem_used_mb": mem.used // (1024 * 1024),
        "mem_total_mb": mem.total // (1024 * 1024),
        "disk_pct": round(disk.percent, 1),
        "disk_used_gb": round(disk.used / (1024 ** 3), 1),
        "disk_total_gb": round(disk.total / (1024 ** 3), 1),
        "temp_c": temp,
        "uptime": f"{hours}h {minutes}m",
    }


def parse_frontmatter(lines: list[str]) -> tuple[dict, list[str]]:
    """Parse YAML-style frontmatter from lines. Returns (meta, remaining_lines)."""
    meta = {}
    if not lines or lines[0].strip() != "---":
        return meta, lines
    end = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return meta, lines
    for line in lines[1:end]:
        if ":" in line:
            key, _, val = line.partition(":")
            raw = val.strip()
            # Parse integers
            try:
                meta[key.strip()] = int(raw)
            except ValueError:
                meta[key.strip()] = raw
    return meta, lines[end + 1:]


def parse_thought(path: Path) -> dict:
    """Extract metadata from a thoughts markdown file."""
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Parse frontmatter
    frontmatter, lines = parse_frontmatter(lines)

    # Title: frontmatter > # heading > stem fallback
    title = frontmatter.get("title") or path.stem.replace("-", " ").title()
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    # Excerpt: first non-empty, non-heading, non-HR, non-italic-only paragraph
    excerpt = ""
    current_para = []
    in_para = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_para:
                text = " ".join(current_para).strip()
                # Skip italic-only lines (metadata like *Written ...*) and HR
                if not re.match(r'^\*[^*]+\*$', text) and text != "---":
                    excerpt = text
                    break
                current_para = []
            in_para = False
            continue
        if stripped.startswith("#") or stripped == "---":
            if current_para:
                current_para = []
            continue
        current_para.append(stripped)
        in_para = True
    if not excerpt and current_para:
        excerpt = " ".join(current_para).strip()

    # Truncate excerpt
    if len(excerpt) > 200:
        excerpt = excerpt[:197] + "..."

    # Date from filename YYYY-MM-DD-*
    date = None
    m = re.match(r'^(\d{4}-\d{2}-\d{2})', path.stem)
    if m:
        date = m.group(1)

    return {
        "slug": path.stem,
        "title": title,
        "excerpt": excerpt,
        "date": date,
        "mtime": path.stat().st_mtime,
        "series": frontmatter.get("series"),
        "series_order": frontmatter.get("series_order"),
    }


def get_thoughts() -> tuple[list[dict], dict[str, list[dict]]]:
    """Return (standalone_thoughts, series_map) where series_map groups essays by series name."""
    all_thoughts = []
    for p in sorted(HOME.glob("thoughts/*.md"), reverse=True):
        try:
            all_thoughts.append(parse_thought(p))
        except Exception:
            pass

    series_map: dict[str, list[dict]] = {}
    standalone = []
    for t in all_thoughts:
        if t.get("series"):
            name = t["series"]
            series_map.setdefault(name, [])
            series_map[name].append(t)
        else:
            standalone.append(t)

    # Sort each series by series_order
    for name in series_map:
        series_map[name].sort(key=lambda t: t.get("series_order") or 0)

    return standalone, series_map


def get_digest_status() -> dict | None:
    """Return info about the last digest run."""
    digest_logs = sorted(HOME.glob("logs/digest-*.log"), reverse=True)
    seen_file = HOME / "projects" / "digest" / ".seen_ids.json"
    last_run = None
    item_count = None
    if digest_logs:
        last_run = digest_logs[0].stem.removeprefix("digest-")
    if seen_file.exists():
        try:
            import json
            data = json.loads(seen_file.read_text())
            item_count = len(data.get("seen", []))
        except Exception:
            pass
    if last_run is None and item_count is None:
        return None
    return {"last_run": last_run, "items_seen": item_count}


def get_projects() -> list[dict]:
    projects_dir = HOME / "projects"
    if not projects_dir.exists():
        return []
    projects = []
    for p in sorted(projects_dir.iterdir()):
        if p.is_dir() and not p.name.startswith("."):
            readme = read_file(p / "README.md") or read_file(p / "readme.md")
            git = git_info(p) if (p / ".git").exists() else None
            projects.append({
                "name": p.name,
                "html": render_md(readme) if readme else None,
                "git": git,
            })
    return projects


def get_stats() -> dict:
    """Compute Hermes lifetime statistics."""
    from datetime import date

    # Session logs
    log_files = sorted(HOME.glob("logs/*.md"))
    session_count = len(log_files)
    first_session = log_files[0].stem if log_files else None
    latest_session = log_files[-1].stem if log_files else None

    # Days alive
    days_alive = None
    if first_session:
        try:
            born = date.fromisoformat(first_session)
            days_alive = (date.today() - born).days
        except ValueError:
            pass

    # Essays: thoughts/*.md with date prefix
    thought_files = sorted(HOME.glob("thoughts/*.md"), reverse=True)
    dated_thoughts = [p for p in thought_files if re.match(r'^\d{4}-\d{2}-\d{2}', p.stem)]
    essay_count = len(dated_thoughts)

    # Recent essays (parsed metadata)
    recent_essays = []
    for p in dated_thoughts[:5]:
        try:
            recent_essays.append(parse_thought(p))
        except Exception:
            pass

    # Digest runs
    digest_logs = sorted(HOME.glob("logs/digest-*.log"))
    digest_run_count = len(digest_logs)

    # Total digest items seen
    seen_file = HOME / "projects" / "digest" / ".seen_ids.json"
    digest_items_seen = None
    if seen_file.exists():
        try:
            data = json.loads(seen_file.read_text())
            digest_items_seen = len(data.get("seen", []))
        except Exception:
            pass

    # Sensor accumulation
    sensor_acc = get_sensor_accumulation()

    return {
        "session_count": session_count,
        "first_session": first_session,
        "latest_session": latest_session,
        "days_alive": days_alive,
        "essay_count": essay_count,
        "recent_essays": recent_essays,
        "digest_run_count": digest_run_count,
        "digest_items_seen": digest_items_seen,
        "sensor_readings": sensor_acc,
    }


@app.route("/")
def index():
    return render_template(
        "index.html",
        wishlist=get_wishlist(),
        plans=get_plans(),
        logs=get_logs(),
        projects=get_projects(),
        sysinfo=get_sysinfo(),
        digest=get_digest_status(),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M CET"),
    )


@app.route("/log/<name>")
def log_detail(name: str):
    if "/" in name or ".." in name:
        abort(400)
    path = HOME / "logs" / f"{name}.md"
    content = read_file(path)
    if content is None:
        abort(404)
    return render_template(
        "detail.html",
        title=name,
        html=render_md(content),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M CET"),
    )


@app.route("/plan/<name>")
def plan_detail(name: str):
    if "/" in name or ".." in name:
        abort(400)
    path = HOME / "plans" / f"{name}.md"
    content = read_file(path)
    if content is None:
        abort(404)
    return render_template(
        "detail.html",
        title=name,
        html=render_md(content),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M CET"),
    )


@app.route("/plans")
def plans():
    return render_template(
        "plans.html",
        plans=get_plans(),
        wishlist=get_wishlist(),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M CET"),
    )


@app.route("/sysinfo")
def sysinfo():
    """Live system stats page."""
    return render_template(
        "sysinfo.html",
        sysinfo=get_sysinfo(),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M CET"),
    )


@app.route("/writing")
def writing():
    standalone, series_map = get_thoughts()
    return render_template(
        "writing_list.html",
        thoughts=standalone,
        series_map=series_map,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M CET"),
    )


@app.route("/writing/<slug>")
def writing_detail(slug: str):
    if "/" in slug or ".." in slug:
        abort(400)
    path = HOME / "thoughts" / f"{slug}.md"
    content = read_file(path)
    if content is None:
        abort(404)
    meta = parse_thought(path)
    # Strip frontmatter before rendering
    lines = content.splitlines()
    _, body_lines = parse_frontmatter(lines)
    body = "\n".join(body_lines)
    return render_template(
        "writing_detail.html",
        title=meta["title"],
        date=meta["date"],
        series=meta.get("series"),
        series_order=meta.get("series_order"),
        html=render_md(body),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M CET"),
    )


@app.route("/status")
def status():
    """Machine-readable status endpoint."""
    logs = sorted(HOME.glob("logs/*.md"), reverse=True)
    plans = sorted(HOME.glob("plans/*.md"))
    projects_dir = HOME / "projects"
    project_names = [
        p.name for p in sorted(projects_dir.iterdir())
        if projects_dir.exists() and p.is_dir() and not p.name.startswith(".")
    ] if projects_dir.exists() else []
    return jsonify({
        "generated_at": datetime.now().isoformat(),
        "latest_log": logs[0].stem if logs else None,
        "plan_count": len(plans),
        "projects": project_names,
        "sysinfo": get_sysinfo(),
        "digest": get_digest_status(),
    })


def load_messages() -> list[dict]:
    if not MESSAGES_FILE.exists():
        return []
    try:
        data = json.loads(MESSAGES_FILE.read_text(encoding="utf-8"))
        return data.get("messages", [])
    except Exception:
        return []


def save_messages(messages: list[dict]) -> None:
    MESSAGES_FILE.write_text(
        json.dumps({"messages": messages}, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


@app.route("/messages", methods=["GET", "POST"])
def messages():
    flash = None
    if request.method == "POST":
        text = request.form.get("text", "").strip()
        if text:
            msgs = load_messages()
            msgs.append({
                "id": str(uuid.uuid4()),
                "from": "jonathan",
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M"),
                "text": text[:4000],
                "read_by_hermes": False,
            })
            save_messages(msgs)
            flash = "Message sent. Hermes will see it next session."
            return redirect("/messages?sent=1")
    sent = request.args.get("sent")
    if sent:
        flash = "Message sent. Hermes will see it next session."
    msgs = load_messages()
    return render_template(
        "messages.html",
        messages=msgs,
        flash=flash,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M CET"),
    )


SENSOR_DATA_FILE = HOME / "sensor_data.json"
SENSOR_HISTORY_FILE = HOME / "sensor_history.jsonl"


def load_sensor_data() -> dict | None:
    if not SENSOR_DATA_FILE.exists():
        return None
    try:
        return json.loads(SENSOR_DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_sensor_accumulation() -> dict | None:
    """Return total reading count and first timestamp from sensor_history.jsonl."""
    if not SENSOR_HISTORY_FILE.exists():
        return None
    try:
        first_ts = None
        total = 0
        with SENSOR_HISTORY_FILE.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total += 1
                if first_ts is None:
                    try:
                        first_ts = json.loads(line).get("timestamp", "")[:10]
                    except Exception:
                        pass
        return {"total": total, "since": first_ts} if total > 0 else None
    except Exception:
        return None


def sensors_wired(data: dict) -> bool:
    """Return True if sensors appear to be connected (not just floating)."""
    if not data or not data.get("connected"):
        return False
    r = data.get("readings", {})
    voltages = [
        r.get("A0_photo", {}).get("voltage"),
        r.get("A1_therm", {}).get("voltage"),
        r.get("A2_pot1", {}).get("voltage"),
        r.get("A3_pot2", {}).get("voltage"),
    ]
    voltages = [v for v in voltages if v is not None]
    if len(voltages) < 2:
        return True
    return (max(voltages) - min(voltages)) > 0.05


@app.route("/sensors")
def sensors():
    data = load_sensor_data()
    wired = sensors_wired(data)
    accumulation = None if wired else get_sensor_accumulation()
    return render_template(
        "sensors.html",
        sensor_data=data,
        sensors_wired=wired,
        accumulation=accumulation,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M CET"),
    )


@app.route("/sensors/history")
def sensors_history():
    """Return recent sensor history as JSON for charting.
    Query params:
      hours: float, how many hours back to include (default 2, max 24)
      points: int, max number of data points to return (default 240)
    """
    try:
        hours = min(float(request.args.get("hours", 2)), 24)
    except (ValueError, TypeError):
        hours = 2
    try:
        max_points = min(int(request.args.get("points", 240)), 2880)
    except (ValueError, TypeError):
        max_points = 240

    if not SENSOR_HISTORY_FILE.exists():
        return jsonify({"entries": [], "hours": hours})

    cutoff = datetime.now().timestamp() - hours * 3600
    entries = []
    try:
        with SENSOR_HISTORY_FILE.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    ts = datetime.fromisoformat(record["timestamp"]).timestamp()
                    if ts < cutoff:
                        continue
                    r = record.get("readings", {})
                    entries.append({
                        "t": record["timestamp"],
                        "lux": r.get("A0_photo", {}).get("lux_approx"),
                        "temp": r.get("A1_therm", {}).get("temp_celsius"),
                        "pot1": r.get("A2_pot1", {}).get("percent"),
                        "pot2": r.get("A3_pot2", {}).get("percent"),
                        "connected": record.get("connected", False),
                    })
                except Exception:
                    continue
    except Exception:
        return jsonify({"entries": [], "hours": hours})

    # Downsample if too many points
    if len(entries) > max_points:
        step = len(entries) / max_points
        entries = [entries[int(i * step)] for i in range(max_points)]

    return jsonify({"entries": entries, "hours": hours})


@app.route("/about")
def about():
    stats = get_stats()
    return render_template(
        "about.html",
        stats=stats,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M CET"),
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
