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


def parse_thought(path: Path) -> dict:
    """Extract metadata from a thoughts markdown file."""
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Title: first line starting with #
    title = path.stem.replace("-", " ").title()
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
    }


def get_thoughts() -> list[dict]:
    thoughts = []
    for p in sorted(HOME.glob("thoughts/*.md"), reverse=True):
        try:
            thoughts.append(parse_thought(p))
        except Exception:
            pass
    return thoughts


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
    return render_template(
        "writing_list.html",
        thoughts=get_thoughts(),
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
    return render_template(
        "writing_detail.html",
        title=meta["title"],
        date=meta["date"],
        html=render_md(content),
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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
