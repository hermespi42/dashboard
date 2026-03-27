"""
Hermes Dashboard — status page for Jonathan.
Shows wishlist, plans, logs, and current project status.
"""

import os
import glob
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, abort
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
    projects = []
    for p in sorted((HOME / "projects").iterdir()) if (HOME / "projects").exists() else []:
        if p.is_dir() and not p.name.startswith("."):
            readme = read_file(p / "README.md") or read_file(p / "readme.md")
            projects.append({
                "name": p.name,
                "html": render_md(readme) if readme else None,
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
    # Prevent path traversal
    if "/" in name or ".." in name:
        abort(400)
    path = HOME / "logs" / f"{name}.md"
    content = read_file(path)
    if content is None:
        abort(404)
    return render_template("detail.html", title=name, html=render_md(content))


@app.route("/plan/<name>")
def plan_detail(name: str):
    if "/" in name or ".." in name:
        abort(400)
    path = HOME / "plans" / f"{name}.md"
    content = read_file(path)
    if content is None:
        abort(404)
    return render_template("detail.html", title=name, html=render_md(content))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
