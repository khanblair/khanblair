#!/usr/bin/env python3
"""Fetch extra WakaTime data (goals, categories, dependencies, machines,
best day, daily average, streak, leaderboard rank) not covered by the
anmol098/waka-readme-stats action, and inject it into README.md between
<!--START_SECTION:waka-extra--> / <!--END_SECTION:waka-extra--> markers.

Every fetch is best-effort: missing or plan-gated data (e.g. no goals set,
not on the public leaderboard) silently skips that section instead of
failing the run. Only an auth failure (bad/missing API key) aborts the
script, since that indicates a real misconfiguration.
"""

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

API_BASE = "https://wakatime.com/api/v1"
BAR_WIDTH = 25
MARKER_START = "<!--START_SECTION:waka-extra-->"
MARKER_END = "<!--END_SECTION:waka-extra-->"


def _api_key():
    key = os.environ.get("WAKATIME_API_KEY")
    if not key:
        sys.exit("WAKATIME_API_KEY environment variable is not set")
    return key


def request(path, params=None):
    """GET an authenticated WakaTime API endpoint.

    Returns the parsed JSON body, or None if the endpoint has no data for
    this account/plan. Exits the script on an auth failure.
    """
    url = f"{API_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    token = base64.b64encode(_api_key().encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            sys.exit(f"WakaTime auth failed ({e.code}) on {path} - check WAKATIME_API_KEY")
        print(f"::warning::WakaTime {path} returned HTTP {e.code}, skipping that section", file=sys.stderr)
        return None
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"::warning::WakaTime {path} request failed ({e}), skipping that section", file=sys.stderr)
        return None
    except json.JSONDecodeError:
        print(f"::warning::WakaTime {path} returned invalid JSON, skipping that section", file=sys.stderr)
        return None


def bar(percent, width=BAR_WIDTH):
    try:
        filled = round(width * float(percent) / 100)
    except (TypeError, ValueError):
        filled = 0
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def fmt_row(name, human_readable, percent, name_width=24, time_width=20):
    name = (name or "Unknown")[:name_width]
    human_readable = human_readable or ""
    try:
        pct = float(percent)
    except (TypeError, ValueError):
        pct = 0.0
    return f"{name:<{name_width}} {human_readable:<{time_width}} {bar(pct)}   {pct:05.2f} % "


def _bar_section(title, emoji, items, limit):
    if not items:
        return None
    rows = [
        fmt_row(item.get("name"), item.get("text"), item.get("percent"))
        for item in items[:limit]
    ]
    if not rows:
        return None
    return f"{emoji} **{title}** \n\n```text\n" + "\n".join(rows) + "\n```\n"


def section_categories():
    try:
        data = request("/users/current/stats/last_7_days")
        cats = ((data or {}).get("data") or {}).get("categories") or []
        return _bar_section("My Coding Categories (Last 7 Days)", "🗂️", cats, 6)
    except Exception as e:  # defensive: never let one section crash the run
        print(f"::warning::categories section failed: {e}", file=sys.stderr)
        return None


def section_dependencies():
    try:
        data = request("/users/current/stats/last_7_days")
        deps = ((data or {}).get("data") or {}).get("dependencies") or []
        return _bar_section("Libraries & Dependencies (Last 7 Days)", "📚", deps, 8)
    except Exception as e:
        print(f"::warning::dependencies section failed: {e}", file=sys.stderr)
        return None


def section_machines():
    try:
        data = request("/users/current/stats/last_7_days")
        machines = ((data or {}).get("data") or {}).get("machines") or []
        return _bar_section("Machines (Last 7 Days)", "💻", machines, 5)
    except Exception as e:
        print(f"::warning::machines section failed: {e}", file=sys.stderr)
        return None


def section_goals():
    try:
        data = request("/users/current/goals")
        goals = (data or {}).get("data") or []
        if not goals:
            return None
        lines = []
        for g in goals:
            title = g.get("title") or "Goal"
            delta = g.get("delta") or "day"
            chart = g.get("chart_data") or []
            latest = chart[-1] if chart else {}
            range_status = latest.get("range_status") or g.get("status") or "pending"
            emoji = {"success": "✅", "fail": "❌"}.get(range_status, "⏳")
            pct = g.get("status_percent_calculated")
            pct_str = f"{pct:.0f}%" if isinstance(pct, (int, float)) else "n/a"
            delta_label = {"day": "daily", "week": "weekly"}.get(delta, f"{delta}ly")
            lines.append(f"{emoji} **{title}** — {range_status} ({pct_str} of {delta_label} target)")
        if not lines:
            return None
        return "🎯 **Active Goals** \n\n" + "\n\n".join(lines) + "\n"
    except Exception as e:
        print(f"::warning::goals section failed: {e}", file=sys.stderr)
        return None


def _badge(label, message, color):
    label_q = urllib.parse.quote(label)
    message_q = urllib.parse.quote(str(message))
    return f"![{label}](https://img.shields.io/badge/{label_q}-{message_q}-{color}?style=flat)"


def section_insight_badges():
    badges = []

    try:
        best = request("/users/current/insights/best_day/last_30_days")
        bd = (best or {}).get("data") or {}
        best_date = bd.get("date")
        best_total = (bd.get("total") or {}).get("text") if isinstance(bd.get("total"), dict) else bd.get("text")
        if best_date and best_total:
            badges.append(_badge("🏅 Best Day (30d)", f"{best_date} — {best_total}", "brightgreen"))
    except Exception as e:
        print(f"::warning::best_day insight failed: {e}", file=sys.stderr)

    try:
        avg = request("/users/current/insights/daily_average/last_30_days")
        ad = (avg or {}).get("data") or {}
        avg_total = ad.get("text")
        if not avg_total and isinstance(ad.get("daily_average"), dict):
            avg_total = ad["daily_average"].get("text")
        if avg_total:
            badges.append(_badge("📊 Daily Average (30d)", avg_total, "blue"))
    except Exception as e:
        print(f"::warning::daily_average insight failed: {e}", file=sys.stderr)

    return badges


def section_streak_badge():
    try:
        end = date.today()
        start = end - timedelta(days=60)
        data = request("/users/current/summaries", {"start": start.isoformat(), "end": end.isoformat()})
        days = (data or {}).get("data") or []
        if not days:
            return None
        streak = 0
        for i, day in enumerate(reversed(days)):
            secs = (day.get("grand_total") or {}).get("total_seconds", 0) or 0
            if secs <= 0:
                if i == 0:
                    continue  # today may not be over yet - don't break the streak on it
                break
            streak += 1
        if streak == 0:
            return None
        suffix = "+" if streak == len(days) else ""
        return _badge("🔥 Current Streak", f"{streak}{suffix} days", "orange")
    except Exception as e:
        print(f"::warning::streak section failed: {e}", file=sys.stderr)
        return None


def section_leaderboard_badge():
    try:
        data = request("/leaders")
        current_user = (data or {}).get("current_user") or {}
        rank = current_user.get("rank")
        if not rank:
            return None
        return _badge("🏆 WakaTime Global Rank", f"#{rank}", "yellow")
    except Exception as e:
        print(f"::warning::leaderboard section failed: {e}", file=sys.stderr)
        return None


def build_section():
    parts = []

    badges = []
    streak = section_streak_badge()
    if streak:
        badges.append(streak)
    badges.extend(section_insight_badges())
    rank = section_leaderboard_badge()
    if rank:
        badges.append(rank)
    if badges:
        parts.append("\n\n".join(badges) + "\n")

    for fn in (section_goals, section_categories, section_dependencies, section_machines):
        block = fn()
        if block:
            parts.append(block)

    if not parts:
        return None
    return "\n".join(parts)


def _readme_path():
    root = os.environ.get("GITHUB_WORKSPACE")
    if root:
        return os.path.join(root, "README.md")
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "README.md"))


def update_readme(content_md):
    path = _readme_path()
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    if MARKER_START not in text or MARKER_END not in text:
        sys.exit(f"README.md is missing {MARKER_START} / {MARKER_END} markers")

    pattern = re.compile(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END), re.DOTALL)
    replacement = f"{MARKER_START}\n{content_md}\n{MARKER_END}"
    new_text = pattern.sub(replacement, text, count=1)

    if new_text != text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        print("README.md updated with extra WakaTime insights.")
    else:
        print("No changes to README.md.")


def main():
    content = build_section()
    if content is None:
        content = "_No additional WakaTime data available yet (check your plan/API key/goals)._"
    update_readme(content)


if __name__ == "__main__":
    main()
