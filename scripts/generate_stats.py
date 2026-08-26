#!/usr/bin/env python3
"""Regenerate the language-distribution charts and the recent-activity list in
README.md from live GitHub data.

Reads only public repositories under USERNAME. No secrets required to read
public data; GITHUB_TOKEN (if present) is used solely to raise the API rate
limit, exactly the token GitHub Actions injects automatically.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

USERNAME = "fsoaz"
API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Approximate linguist-style colors, tuned to stay legible on both a light
# and a dark background.
LANGUAGE_COLORS = {
    "Python": "#4B8BBE",
    "TypeScript": "#3178C6",
    "JavaScript": "#E8B93F",
    "CSS": "#8B5CF6",
    "HTML": "#E4572E",
    "Kotlin": "#7F52FF",
    "Shell": "#4EAA25",
    "PHP": "#6C7CB0",
    "Other": "#8B949E",
}


def api_get(path: str):
    req = urllib.request.Request(f"{API}{path}", headers={"Accept": "application/vnd.github+json"})
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def fetch_public_repos() -> list[dict]:
    repos, page = [], 1
    while True:
        batch = api_get(f"/users/{USERNAME}/repos?per_page=100&page={page}&type=owner")
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return [r for r in repos if not r["fork"] and not r["archived"]]


def aggregate_languages(repos: list[dict]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for repo in repos:
        try:
            langs = api_get(f"/repos/{USERNAME}/{repo['name']}/languages")
        except urllib.error.HTTPError:
            continue
        for lang, byte_count in langs.items():
            totals[lang] = totals.get(lang, 0) + byte_count
    return totals


def bucket_languages(totals: dict[str, int], top_n: int = 6) -> list[tuple[str, int]]:
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    head, tail = ranked[:top_n], ranked[top_n:]
    buckets = list(head)
    other = sum(v for _, v in tail)
    if other:
        buckets.append(("Other", other))
    return buckets


def render_language_svg(buckets: list[tuple[str, int]], *, dark: bool) -> str:
    total = sum(v for _, v in buckets) or 1
    width, bar_height, radius = 800, 14, 7
    bg = "#0d1117" if dark else "#ffffff"
    track = "#21262d" if dark else "#eaeef2"
    text_color = "#c9d1d9" if dark else "#24292f"
    muted = "#8b949e" if dark else "#57606a"

    segments = []
    x = 0.0
    for name, value in buckets:
        w = (value / total) * width
        color = LANGUAGE_COLORS.get(name, LANGUAGE_COLORS["Other"])
        segments.append(f'<rect x="{x:.2f}" y="0" width="{w:.2f}" height="{bar_height}" fill="{color}"/>')
        x += w

    cols, col_width, row_height = 3, width / 3, 26
    legend = []
    for i, (name, value) in enumerate(buckets):
        pct = round((value / total) * 100)
        col, row = i % cols, i // cols
        lx, ly = col * col_width, bar_height + 22 + row * row_height
        color = LANGUAGE_COLORS.get(name, LANGUAGE_COLORS["Other"])
        legend.append(
            f'<rect x="{lx:.1f}" y="{ly - 10}" width="10" height="10" rx="2" fill="{color}"/>'
            f'<text x="{lx + 16:.1f}" y="{ly - 1}" font-family="ui-monospace,Menlo,Consolas,monospace" '
            f'font-size="13" fill="{text_color}">{name}</text>'
            f'<text x="{lx + 16 + len(name) * 9 + 10:.1f}" y="{ly - 1}" '
            f'font-family="ui-monospace,Menlo,Consolas,monospace" font-size="13" fill="{muted}">{pct}%</text>'
        )

    rows = -(-len(buckets) // cols)
    height = bar_height + 22 + rows * row_height + 8

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="Language distribution across public repositories">
  <rect x="0" y="0" width="{width}" height="{height}" fill="{bg}"/>
  <rect x="0" y="0" width="{width}" height="{bar_height}" rx="{radius}" fill="{track}"/>
  <clipPath id="bar-clip-{'dark' if dark else 'light'}"><rect x="0" y="0" width="{width}" height="{bar_height}" rx="{radius}"/></clipPath>
  <g clip-path="url(#bar-clip-{'dark' if dark else 'light'})">
    {''.join(segments)}
  </g>
  {''.join(legend)}
</svg>'''


def render_recent_activity(repos: list[dict], limit: int = 5) -> str:
    ranked = sorted(
        (r for r in repos if r["name"] != USERNAME),
        key=lambda r: r["pushed_at"],
        reverse=True,
    )[:limit]
    lines = []
    for repo in ranked:
        pushed = datetime.fromisoformat(repo["pushed_at"].replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - pushed).days
        when = "today" if days == 0 else ("yesterday" if days == 1 else f"{days}d ago")
        lang = f"`{repo['language']}`" if repo.get("language") else "—"
        lines.append(f"- **[{repo['name']}]({repo['html_url']})** {lang} · _{when}_")
    return "\n".join(lines) if lines else "_No recent public activity._"


def splice(readme: str, marker: str, content: str) -> str:
    pattern = re.compile(
        rf"(<!-- {marker}:START -->)(.*?)(<!-- {marker}:END -->)", re.DOTALL
    )
    if not pattern.search(readme):
        print(f"warning: markers for {marker} not found in README.md", file=sys.stderr)
        return readme
    return pattern.sub(lambda m: f"{m.group(1)}\n{content}\n{m.group(3)}", readme)


def main() -> None:
    repos = fetch_public_repos()
    totals = aggregate_languages(repos)
    buckets = bucket_languages(totals)

    os.makedirs(os.path.join(ROOT, "assets"), exist_ok=True)
    with open(os.path.join(ROOT, "assets", "languages-dark.svg"), "w") as f:
        f.write(render_language_svg(buckets, dark=True))
    with open(os.path.join(ROOT, "assets", "languages-light.svg"), "w") as f:
        f.write(render_language_svg(buckets, dark=False))

    readme_path = os.path.join(ROOT, "README.md")
    with open(readme_path) as f:
        readme = f.read()
    readme = splice(readme, "RECENT_ACTIVITY", render_recent_activity(repos))
    with open(readme_path, "w") as f:
        f.write(readme)

    print(f"Aggregated {len(repos)} public repositories, {len(buckets)} language buckets.")


if __name__ == "__main__":
    main()
