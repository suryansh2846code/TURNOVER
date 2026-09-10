"""Generate the human-readable Markdown/JSON mirror FROM SQLite.

The export is a projection, never a second source of truth. Re-running it fully
regenerates `brain-export/`. Structured fields live in YAML frontmatter; prose
in the body — so a future 'import edits' can round-trip frontmatter safely.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import freshness
from .store import CanonicalStore


def _fm(d: dict) -> str:
    lines = ["---"]
    for k, v in d.items():
        lines.append(f"{k}: {json.dumps(v) if isinstance(v, (list, dict)) else v}")
    lines.append("---\n")
    return "\n".join(lines)


def export(store: CanonicalStore, out_dir: Path | None = None) -> dict:
    from ...config import get_settings
    root = Path(out_dir) if out_dir else (get_settings().home / "brain-export")
    root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    # About You
    au = store.current_claims(entity_id=None, section="about_you")
    body = [_fm({"section": "about_you", "generated_at": datetime.now(timezone.utc).isoformat()}),
            "# About You\n"]
    for c in au:
        f = freshness.compute(c)
        tag = f" _({f})_" if f != "fresh" else ""
        conf = "" if c["confidence"] == "confirmed" else " _(inferred)_"
        body.append(f"- **{c['type']}**: {c['value']}{conf}{tag}")
    p = root / "about-you.md"
    p.write_text("\n".join(body)); written.append(str(p))

    # People & Work entities
    for etype, folder in (("person", "people"), ("project", "work"),
                          ("organization", "work")):
        d = root / folder
        d.mkdir(exist_ok=True)
        for e in store.list_entities(type=etype):
            claims = store.current_claims(entity_id=e["id"])
            idents = store.identifiers_for(e["id"])
            fmn = {"id": e["id"], "type": e["type"], "name": e["canonical_name"],
                   "identifiers": [f"{i['kind']}:{i['value_normalized']}" for i in idents]}
            lines = [_fm(fmn), f"# {e['canonical_name']}\n"]
            for c in claims:
                lines.append(f"- **{c['type']}**: {c['value']}"
                             + ("" if c["confidence"] == "confirmed" else " _(inferred)_"))
            tasks = store.open_tasks(entity_id=e["id"])
            if tasks:
                lines.append("\n## Open")
                for t in tasks:
                    lines.append(f"- [ ] {t['title']}"
                                 + (f" (due {t['due_at']})" if t.get("due_at") else ""))
            slug = "".join(ch if ch.isalnum() else "-"
                           for ch in e["canonical_name"].lower()).strip("-") or e["id"][:8]
            fp = d / f"{slug}.md"
            fp.write_text("\n".join(lines)); written.append(str(fp))

    # Timeline grouped by year
    events = store.timeline(limit=1000)
    by_year: dict[str, list[dict]] = {}
    for ev in events:
        by_year.setdefault((ev["occurred_at"] or "0000")[:4], []).append(ev)
    tl = root / "timeline"
    tl.mkdir(exist_ok=True)
    for year, evs in sorted(by_year.items(), reverse=True):
        lines = [_fm({"section": "timeline", "year": year}), f"# Timeline {year}\n"]
        for ev in sorted(evs, key=lambda e: e["occurred_at"], reverse=True):
            lines.append(f"- **{ev['occurred_at']}** ({ev['event_type']}): {ev['summary']}")
        fp = tl / f"{year}.md"
        fp.write_text("\n".join(lines)); written.append(str(fp))

    # machine-readable snapshot
    snap = {"about_you": au,
            "entities": store.list_entities(),
            "events": events, "stats": store.stats()}
    jp = root / "brain.json"
    jp.write_text(json.dumps(snap, indent=2, default=str)); written.append(str(jp))
    return {"files": written, "dir": str(root)}
