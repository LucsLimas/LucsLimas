#!/usr/bin/env python3
"""Generate the FOXHOUND profile report using public GitHub API data."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
MISSIONS_FILE = ROOT / "data" / "missions.json"
USERNAME = os.getenv("GITHUB_USERNAME", "LucsLimas")
API = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "foxhound-profile-updater",
}
token = os.getenv("GITHUB_TOKEN")
if token:
    HEADERS["Authorization"] = f"Bearer {token}"

def get_json(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(
                f"GitHub user/recurso não encontrado: {url}. "
                f"Confirme GITHUB_USERNAME (configurado como {USERNAME!r})."
            ) from exc
        if exc.code == 403:
            raise RuntimeError(
                "A API do GitHub limitou a requisição. Tente novamente mais tarde; "
                "nenhum dado foi publicado."
            ) from exc
        raise RuntimeError(f"GitHub API retornou HTTP {exc.code} para {url}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Falha de rede consultando a API do GitHub: {exc}") from exc

def replace_section(text: str, name: str, content: str) -> str:
    start = f"<!-- {name}:START -->"
    end = f"<!-- {name}:END -->"
    if start not in text or end not in text:
        raise RuntimeError(f"Marcadores {start} / {end} não encontrados no README.")
    before, remainder = text.split(start, 1)
    _, after = remainder.split(end, 1)
    return before + start + "\n" + content.rstrip() + "\n" + end + after

def rank_for(xp: int):
    ranks = [
        (0, "RECRUIT"),
        (250, "FIELD OPERATIVE"),
        (600, "ELITE OPERATIVE"),
        (1200, "FOXHOUND"),
        (2200, "BIG BOSS"),
        (4000, "LEGENDARY SOLDIER"),
    ]
    current = ranks[0]
    next_rank = None
    for item in ranks:
        if xp >= item[0]:
            current = item
        elif next_rank is None:
            next_rank = item
    if next_rank is None:
        return current[1], "MAX RANK REACHED", 100
    progress = int((xp - current[0]) / (next_rank[0] - current[0]) * 100)
    return current[1], f"{next_rank[1]} at {next_rank[0]:,} XP", max(0, min(100, progress))

def main():
    user = get_json(f"{API}/users/{urllib.parse.quote(USERNAME)}")
    repos = get_json(f"{API}/users/{urllib.parse.quote(USERNAME)}/repos?per_page=100&sort=updated")
    if not isinstance(repos, list):
        raise RuntimeError("Resposta inesperada ao consultar repositórios.")

    # GitHub's public events endpoint exposes at most the latest 300 events.
    # We label this explicitly instead of presenting it as all-time activity.
    events = get_json(f"{API}/users/{urllib.parse.quote(USERNAME)}/events/public?per_page=100")
    if not isinstance(events, list):
        raise RuntimeError("Resposta inesperada ao consultar eventos públicos.")

    owned_repos = [r for r in repos if not r.get("fork", False)]
    stars = sum(int(r.get("stargazers_count") or 0) for r in repos)
    pushes = sum(1 for e in events if e.get("type") == "PushEvent")
    prs = sum(1 for e in events if e.get("type") == "PullRequestEvent")
    issues = sum(1 for e in events if e.get("type") == "IssuesEvent")
    public_events = len(events)

    try:
        mission_data = json.loads(MISSIONS_FILE.read_text(encoding="utf-8"))
        missions = mission_data.get("missions", [])
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Não foi possível ler {MISSIONS_FILE}: {exc}") from exc

    mission_xp = sum(int(m.get("bonus_xp", 0)) for m in missions if m.get("completed") is True)
    # Formula is intentionally transparent and modest; all-time counters are
    # not fabricated from the limited public-events endpoint.
    activity_xp = pushes * 5 + prs * 20 + issues * 10
    profile_xp = len(owned_repos) * 20 + stars * 2
    xp = profile_xp + activity_xp + mission_xp
    rank, next_rank, progress = rank_for(xp)

    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    stats = f"""| INTEL | VALUE |
|---|---:|
| Public repositories (owned, excluding forks) | **{len(owned_repos)}** |
| Stars received across public repositories | **{stars}** |
| Push events in latest public-event sample | **{pushes}** |
| Pull request events in latest public-event sample | **{prs}** |
| Issue events in latest public-event sample | **{issues}** |
| Public events returned by GitHub | **{public_events} / up to 300 available** |
| Base XP (owned repos × 20 + stars × 2) | **{profile_xp} XP** |
| Activity XP (push × 5 + PR × 20 + issue × 10) | **{activity_xp} XP** |
| Mission bonus XP | **{mission_xp} XP** |
| **TOTAL CAMPAIGN XP** | **{xp} XP** |

**Rank progress:** `{progress}%` toward the next promotion  
`{next_rank}`

<sub>Last intel update: {updated}. Events are a recent sample, not an all-time total; GitHub only returns a limited public event history. Star counts are summed across the repositories returned by the public repositories endpoint (up to 100).</sub>"""

    if missions:
        rows = ["| ID | MISSION | STATUS | BONUS | EVIDENCE |", "|---|---|---|---:|---|"]
        for m in missions:
            done = m.get("completed") is True
            status = "✅ CLEARED" if done else "⬜ ACTIVE"
            title = str(m.get("title", "Untitled")).replace("|", "\\|")
            desc = str(m.get("description", "")).replace("|", "\\|")
            evidence = str(m.get("evidence_url", "")).strip()
            evidence_md = f"[proof]({evidence})" if evidence.startswith(("https://", "http://")) else "—"
            rows.append(f"| `{m.get('id','?')}` | **{title}**<br/><sub>{desc}</sub> | {status} | +{int(m.get('bonus_xp',0))} XP | {evidence_md} |")
        mission_md = "\n".join(rows)
    else:
        mission_md = "Nenhuma missão configurada em `data/missions.json`."

    achievements = []
    def award(ok, title, desc):
        if ok:
            achievements.append(f"- 🏅 **{title}** — {desc}")
    award(len(owned_repos) >= 1, "First Insertion", "pelo menos um repositório próprio público.")
    award(len(owned_repos) >= 5, "Jungle Veteran", "cinco repositórios próprios públicos.")
    award(stars >= 10, "Signal Detected", "10 ou mais estrelas somadas.")
    award(pushes >= 5, "Active Patrol", "cinco ou mais eventos de push na amostra recente.")
    award(prs >= 1, "Teamwork", "ao menos um evento público de pull request na amostra.")
    award(sum(1 for m in missions if m.get("completed") is True) >= 1, "Mission Accomplished", "primeira missão marcada como concluída.")
    award(sum(1 for m in missions if m.get("completed") is True) >= 3, "Snake Eater", "três missões concluídas.")
    achievement_md = "\n".join(achievements) if achievements else "_Nenhuma condecoração desbloqueada ainda. Continue a operação._"

    text = README.read_text(encoding="utf-8")
    text = text.replace("`<!-- RANK -->`", f"`{rank}`")
    text = text.replace("`<!-- XP -->`", f"`{xp:,} XP`")
    text = text.replace("`<!-- NEXT_RANK -->`", f"`{next_rank}`")
    text = replace_section(text, "STATS", stats)
    text = replace_section(text, "MISSIONS", mission_md)
    text = replace_section(text, "ACHIEVEMENTS", achievement_md)
    README.write_text(text, encoding="utf-8")
    print(f"FOXHOUND report generated: {rank}, {xp} XP, updated {updated}")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
