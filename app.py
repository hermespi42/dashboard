"""
Hermes Dashboard — status page for Jonathan.
Shows wishlist, plans, logs, and current project status.
"""

import subprocess
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, abort, jsonify
from markdown_it import MarkdownIt

app = Flask(__name__)
HOME = Path("/home/hermes")
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
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
