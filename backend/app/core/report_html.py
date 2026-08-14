"""
Premium, printable HTML audit report (spec 23, extended).

Self-contained and rendered through Jinja2 with autoescaping on, so nothing
scraped from a third-party site can inject markup into the report (spec 45).

Covers: executive summary, the 9-card premium scorecard (Overall + Technical
SEO + On-Page SEO + Off-Page/Authority + Performance + Accessibility +
Security + UX + Conversion), a severity/pass-fail breakdown, every detected
issue grouped by category with evidence and a recommended fix, a prioritised
action plan, and the original contact/pages sections. Every number here
traces back to a Finding produced by audit_checks.py - nothing is invented to
fill a section; empty sections say so plainly (e.g. off-page authority data
that requires a paid backlink index is labelled "not available", never
estimated).
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, select_autoescape

from ..settings import REPORT_DIR
from .audit_checks import Finding
from .scoring import (
    AUDIT_CATEGORIES,
    AUDIT_CATEGORY_LABELS,
    AUDIT_CATEGORY_WHY,
    audit_category_of,
    priority_for,
)

_env = Environment(autoescape=select_autoescape(["html", "xml"]), trim_blocks=True, lstrip_blocks=True)

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
SEVERITY_LABEL = {"high": "Critical", "medium": "High priority", "low": "Warning"}

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Website audit — {{ business.name }}</title>
<style>
  :root{
    --bg:#f6f7fb; --surface:#ffffff; --ink:#131722; --muted:#5b6478; --line:#e4e7ef;
    --brand:#3b5bdb; --brand-soft:#eef2ff;
    --high:#d64545; --high-bg:#fdecec; --med:#c2790a; --med-bg:#fdf4e3;
    --low:#3f7d58; --low-bg:#ecf6f0; --shadow:0 1px 2px rgba(16,24,40,.05),0 4px 16px rgba(16,24,40,.05);
    --green:#2f7d54; --green-bg:#ecf6f0; --yellow:#9c7a0a; --yellow-bg:#fdf8e3;
    --orange:#b3620c; --orange-bg:#fdf1e3; --red:#c53434; --red-bg:#fdecec;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    -webkit-font-smoothing:antialiased;}
  .wrap{max-width:1060px;margin:0 auto;padding:32px 20px 64px}
  .card{background:var(--surface);border:1px solid var(--line);border-radius:14px;
    padding:26px;margin-bottom:20px;box-shadow:var(--shadow)}
  header.card{background:linear-gradient(135deg,#1e2537 0%,#2d3855 100%);color:#fff;border:none}
  header .eyebrow{font-size:11px;letter-spacing:.14em;text-transform:uppercase;opacity:.72;margin:0 0 8px}
  header h1{margin:0 0 6px;font-size:27px;line-height:1.25;letter-spacing:-.02em}
  header .sub{opacity:.82;font-size:14px;margin:0}
  header .sub a{color:#a9c0ff}
  h2{font-size:16px;margin:0 0 16px;letter-spacing:-.01em}
  h2 .count{color:var(--muted);font-weight:400}
  h3{font-size:14px;margin:0}
  .lede{font-size:15px;color:#333b4d;margin:0 0 4px;line-height:1.65}
  .scoregrid{display:grid;grid-template-columns:auto 1fr;gap:28px;align-items:center}
  @media(max-width:620px){.scoregrid{grid-template-columns:1fr;gap:18px}}
  .dial{width:132px;height:132px;border-radius:50%;display:grid;place-items:center;
    background:conic-gradient(var(--dial-color) calc(var(--pct)*1%), #e9ecf4 0);}
  .dial.sm{width:84px;height:84px}
  .dial .inner{width:104px;height:104px;border-radius:50%;background:var(--surface);
    display:grid;place-items:center;text-align:center}
  .dial.sm .inner{width:66px;height:66px}
  .dial .num{font-size:32px;font-weight:700;letter-spacing:-.03em;line-height:1}
  .dial.sm .num{font-size:20px}
  .dial .den{font-size:11px;color:var(--muted);margin-top:2px}
  .dial.sm .den{font-size:9px}
  .tierbadge{display:inline-block;padding:5px 12px;border-radius:999px;font-size:12px;
    font-weight:600;letter-spacing:.02em}
  .bars{display:flex;flex-direction:column;gap:11px}
  .bar-row{display:grid;grid-template-columns:150px 1fr 62px;gap:12px;align-items:center;font-size:13px}
  @media(max-width:620px){.bar-row{grid-template-columns:110px 1fr 52px;font-size:12px}}
  .track{height:8px;background:#eef0f6;border-radius:99px;overflow:hidden}
  .fill{height:100%;border-radius:99px;background:linear-gradient(90deg,#4c6ef5,#5f3dc4)}
  .fill.green{background:linear-gradient(90deg,#3f9d6e,#2f7d54)}
  .fill.yellow{background:linear-gradient(90deg,#e0b93e,#9c7a0a)}
  .fill.orange{background:linear-gradient(90deg,#e8913a,#b3620c)}
  .fill.red{background:linear-gradient(90deg,#e05a5a,#c53434)}
  .barval{text-align:right;color:var(--muted);font-variant-numeric:tabular-nums}
  .problem{border:1px solid var(--line);border-left-width:4px;border-radius:10px;
    padding:16px 18px;margin-bottom:12px;background:#fcfcfe}
  .problem.high{border-left-color:var(--high)}
  .problem.medium{border-left-color:var(--med)}
  .problem.low{border-left-color:var(--low)}
  .problem h3{margin:0 0 6px;font-size:15px;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
  .sev{font-size:10px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;
    padding:3px 8px;border-radius:5px}
  .sev.high{background:var(--high-bg);color:var(--high)}
  .sev.medium{background:var(--med-bg);color:var(--med)}
  .sev.low{background:var(--low-bg);color:var(--low)}
  .pri{font-size:10px;font-weight:700;padding:3px 8px;border-radius:5px;background:#eef0f6;color:var(--muted)}
  .cat-chip{font-size:10px;font-weight:600;padding:3px 8px;border-radius:5px;background:var(--brand-soft);color:var(--brand)}
  .problem p{margin:0 0 8px;color:#333b4d;font-size:14px}
  .why{font-size:13px;color:var(--muted);margin:0 0 8px;font-style:italic}
  .rec{background:var(--brand-soft);border-radius:8px;padding:11px 13px;font-size:13.5px;color:#2b3a6b}
  .rec b{color:#1c2b57}
  .meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}
  .meta div{font-size:13px}
  .meta dt{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.07em;margin-bottom:3px}
  .meta dd{margin:0;font-weight:500;word-break:break-word}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
  th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.06em}
  code{background:#f1f3f9;padding:1px 6px;border-radius:4px;font-size:12.5px;word-break:break-all}
  .pill{display:inline-block;padding:2px 9px;border-radius:99px;font-size:11.5px;font-weight:600}
  .pill.ok{background:var(--low-bg);color:var(--low)}
  .pill.warn{background:var(--med-bg);color:var(--med)}
  .pill.bad{background:var(--high-bg);color:var(--high)}
  .pill.neutral{background:#eef0f6;color:var(--muted)}
  .note{font-size:12.5px;color:var(--muted);margin-top:14px;padding-top:14px;border-top:1px solid var(--line)}
  footer{text-align:center;color:var(--muted);font-size:12px;margin-top:26px;line-height:1.7}
  ul.evidence{margin:8px 0 0;padding-left:18px;font-size:12.5px;color:var(--muted)}
  .kpirow{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin-bottom:4px}
  .kpi{border:1px solid var(--line);border-radius:10px;padding:14px 16px;background:#fcfcfe}
  .kpi .n{font-size:24px;font-weight:700;letter-spacing:-.02em}
  .kpi .l{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-top:2px}
  .scorecards{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px}
  .scorecard{border:1px solid var(--line);border-radius:12px;padding:16px;background:#fcfcfe}
  .scorecard .top{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
  .scorecard .name{font-size:12.5px;font-weight:600;color:var(--ink)}
  .band{font-size:10px;font-weight:700;padding:3px 8px;border-radius:99px;letter-spacing:.03em}
  .band.green{background:var(--green-bg);color:var(--green)}
  .band.yellow{background:var(--yellow-bg);color:var(--yellow)}
  .band.orange{background:var(--orange-bg);color:var(--orange)}
  .band.red{background:var(--red-bg);color:var(--red)}
  .band.unknown{background:#eef0f6;color:var(--muted)}
  .scorecard .score{font-size:26px;font-weight:700;letter-spacing:-.02em;margin-bottom:6px}
  .scorecard .why{margin:8px 0 0;font-size:11.5px;color:var(--muted);font-style:normal;line-height:1.5}
  .passfail{display:flex;flex-wrap:wrap;gap:8px}
  .passfail .chip{display:flex;align-items:center;gap:6px;font-size:12.5px;padding:6px 11px;
    border-radius:8px;background:#fcfcfe;border:1px solid var(--line)}
  .action-item{display:grid;grid-template-columns:34px 1fr;gap:12px;padding:12px 0;
    border-bottom:1px solid var(--line)}
  .action-item:last-child{border-bottom:none}
  .action-num{width:26px;height:26px;border-radius:50%;background:var(--brand-soft);color:var(--brand);
    display:grid;place-items:center;font-weight:700;font-size:12px}
  .disclosure{background:#f8f9fc;border:1px dashed var(--line-strong,#ccd3e0);border-radius:10px;
    padding:12px 14px;font-size:12.5px;color:var(--muted);margin-top:10px}
  .cat-nav{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px}
  .cat-nav a{font-size:12px;padding:6px 12px;border-radius:99px;background:#eef0f6;color:var(--ink-2,#414a5e);
    text-decoration:none;font-weight:500}
  @media print{body{background:#fff}.card{box-shadow:none;break-inside:avoid}.cat-nav{display:none}}
</style>
</head>
<body>
<div class="wrap">

  <header class="card">
    <p class="eyebrow">Website audit report</p>
    <h1>{{ business.name }}</h1>
    <p class="sub">
      {% if audit.website %}<a href="{{ audit.website }}" rel="noopener nofollow">{{ audit.website }}</a>{% else %}No website found{% endif %}
      {% if business.location %} &nbsp;·&nbsp; {{ business.location }}{% endif %}
      {% if business.category %} &nbsp;·&nbsp; {{ business.category }}{% endif %}
      &nbsp;·&nbsp; Generated {{ generated_at }}
    </p>
  </header>

  {% if scorecard %}
  <section class="card">
    <h2>Executive summary</h2>
    <p class="lede">{{ executive_summary }}</p>
    <div class="kpirow" style="margin-top:16px">
      <div class="kpi"><div class="n">{{ scorecard.overall_score }}<span style="font-size:14px;color:var(--muted)">/100</span></div><div class="l">Overall score</div></div>
      <div class="kpi"><div class="n" style="color:var(--high)">{{ findings.critical|length }}</div><div class="l">Critical issues</div></div>
      <div class="kpi"><div class="n" style="color:var(--med)">{{ findings.high|length }}</div><div class="l">High priority</div></div>
      <div class="kpi"><div class="n" style="color:var(--low)">{{ findings.warnings|length }}</div><div class="l">Warnings</div></div>
      <div class="kpi"><div class="n">{{ scorecard.pass_fail.passed_count }}<span style="font-size:14px;color:var(--muted)">/{{ scorecard.pass_fail.total_checked }}</span></div><div class="l">Checks passed</div></div>
    </div>
  </section>

  <section class="card">
    <h2>Category scorecards <span class="count">— higher is better</span></h2>
    <div class="scorecards">
      {% for c in scorecard.categories %}
      <div class="scorecard">
        <div class="top">
          <span class="name">{{ c.label }}</span>
          <span class="band {{ c.band.key }}">{{ c.band.label }}</span>
        </div>
        <div class="score" style="color:{{ c.band.fg }}">{{ c.health }}<span style="font-size:14px;color:var(--muted)">/100</span></div>
        <div class="track"><span class="fill {{ c.band.key }}" style="width:{{ c.health }}%"></span></div>
        <p class="why">{{ c.why_it_matters }}</p>
      </div>
      {% endfor %}
    </div>
  </section>

  <div class="cat-nav">
    {% for cat in category_sections %}
    <a href="#cat-{{ cat.key }}">{{ cat.label }} ({{ cat.findings|length }})</a>
    {% endfor %}
  </div>

  <section class="card">
    <h2>Passed checks <span class="count">— {{ scorecard.pass_fail.passed_count }} of {{ scorecard.pass_fail.total_checked }}</span></h2>
    {% if scorecard.pass_fail.passed %}
    <div class="passfail">
      {% for p in scorecard.pass_fail.passed %}
      <span class="chip">✓ {{ p.label }}</span>
      {% endfor %}
    </div>
    {% else %}
    <p class="small" style="color:var(--muted)">No checks in this catalogue passed on this site.</p>
    {% endif %}
  </section>
  {% endif %}

  {% for group in [('Critical issues', findings.critical), ('High-priority issues', findings.high), ('Warnings', findings.warnings)] %}
  {% if group[1] %}
  <section class="card">
    <h2>{{ group[0] }} <span class="count">— {{ group[1]|length }}</span></h2>
    {% for p in group[1] %}
    <article class="problem {{ p.severity }}">
      <h3>
        <span class="sev {{ p.severity }}">{{ p.severity_label }}</span>
        <span class="cat-chip">{{ p.category_label }}</span>
        {{ p.title }}
      </h3>
      <p>{{ p.detail }}</p>
      {% if p.recommendation %}<div class="rec"><b>Recommended fix:</b> {{ p.recommendation }}</div>{% endif %}
      {% if p.evidence_lines %}
      <ul class="evidence">{% for line in p.evidence_lines %}<li>{{ line }}</li>{% endfor %}</ul>
      {% endif %}
    </article>
    {% endfor %}
  </section>
  {% endif %}
  {% endfor %}

  {% if findings.action_plan %}
  <section class="card">
    <h2>Prioritized action plan <span class="count">— top {{ findings.action_plan|length }} by priority</span></h2>
    {% for a in findings.action_plan %}
    <div class="action-item">
      <div class="action-num">{{ loop.index }}</div>
      <div>
        <div style="display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;margin-bottom:3px">
          <strong style="font-size:13.5px">{{ a.title }}</strong>
          <span class="pri">{{ a.priority }}</span>
          <span class="cat-chip">{{ a.category_label }}</span>
        </div>
        <p style="margin:0;font-size:13px;color:var(--muted)">{{ a.recommendation or a.detail }}</p>
      </div>
    </div>
    {% endfor %}
  </section>
  {% endif %}

  {% if not scorecard %}
  <section class="card">
    <div class="scoregrid">
      <div class="dial" style="--pct:{{ audit.score or 0 }};--dial-color:{{ dial_color }}">
        <div class="inner">
          <div class="num">{{ audit.score if audit.score is not none else '—' }}</div>
          <div class="den">opportunity</div>
        </div>
      </div>
      <div>
        <p style="margin:0 0 12px">
          <span class="tierbadge" style="background:{{ tier_bg }};color:{{ tier_fg }}">
            {{ audit.opportunity_tier or 'Not scored' }} opportunity
          </span>
        </p>
        <p class="note" style="margin-top:0;border-top:none;padding-top:0">
          {{ audit.audit_error or 'This business could not be fully audited. See below for what was checked.' }}
        </p>
      </div>
    </div>
  </section>
  {% endif %}

  {% for cat in category_sections %}
  <section class="card" id="cat-{{ cat.key }}">
    <h2>{{ cat.label }} <span class="count">— {{ cat.findings|length }} finding{{ 's' if cat.findings|length != 1 else '' }}</span></h2>
    {% if cat.findings %}
      {% for p in cat.findings %}
      <article class="problem {{ p.severity }}">
        <h3>
          <span class="sev {{ p.severity }}">{{ p.severity_label }}</span>
          <span class="pri">{{ p.priority }}</span>
          {{ p.title }}
        </h3>
        <p>{{ p.detail }}</p>
        {% if p.why_it_matters %}<p class="why">Why it matters: {{ p.why_it_matters }}</p>{% endif %}
        {% if p.recommendation %}
        <div class="rec"><b>Recommended fix:</b> {{ p.recommendation }}</div>
        {% endif %}
        {% if p.evidence_lines %}
        <ul class="evidence">
          {% for line in p.evidence_lines %}<li>{{ line }}</li>{% endfor %}
        </ul>
        {% endif %}
      </article>
      {% endfor %}
    {% else %}
      <p style="margin:0;color:var(--muted)">No evidence-backed issues were detected in this category.</p>
    {% endif %}
    {% if cat.key == 'offpage' %}
    <div class="disclosure">
      <b>Not available:</b> backlink count, referring domains and domain-authority-style scores
      require a paid third-party index (e.g. Ahrefs, Moz, Majestic, SEMrush). None is configured for
      this audit, so none of that is estimated or fabricated here — only what was directly observed
      on the site itself (linked social profiles, structured-data entity links) is reported above.
    </div>
    {% endif %}
  </section>
  {% endfor %}

  {% if not category_sections and problems %}
  <section class="card">
    <h2>Detected problems <span class="count">— {{ problems|length }} found</span></h2>
    {% for p in problems %}
    <article class="problem {{ p.severity }}">
      <h3>
        <span class="sev {{ p.severity }}">{{ p.severity }}</span>
        {{ p.title }}
      </h3>
      <p>{{ p.detail }}</p>
      {% if p.recommendation %}
      <div class="rec"><b>Recommended fix:</b> {{ p.recommendation }}</div>
      {% endif %}
      {% if p.evidence_lines %}
      <ul class="evidence">
        {% for line in p.evidence_lines %}<li>{{ line }}</li>{% endfor %}
      </ul>
      {% endif %}
    </article>
    {% endfor %}
  </section>
  {% elif not category_sections %}
  <section class="card">
    <h2>Detected problems</h2>
    <p style="margin:0;color:var(--muted)">
      No evidence-backed problems were detected within the checks this audit performs.
      No issues have been invented to fill this section.
    </p>
  </section>
  {% endif %}

  <section class="card">
    <h2>What was measured</h2>
    <table>
      <tbody>
        {% for row in measured %}
        <tr>
          <th style="width:42%">{{ row.label }}</th>
          <td>{{ row.value }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    <p class="note">{{ method_note }}</p>
  </section>

  <section class="card">
    <h2>Contact options found</h2>
    <div class="meta">
      {% for c in contacts %}
      <div>
        <dt>{{ c.label }}</dt>
        <dd>{{ c.value }}{% if c.status %} <span class="pill {{ c.pill }}">{{ c.status }}</span>{% endif %}</dd>
      </div>
      {% endfor %}
    </div>
    <p class="note">
      Contact details listed here were found publicly on the business's own website or supplied
      in the source data. Nothing was guessed or constructed.
    </p>
  </section>

  {% if pages %}
  <section class="card">
    <h2>Pages reviewed <span class="count">— {{ pages|length }}</span></h2>
    <table>
      <thead><tr><th>Type</th><th>URL</th><th style="width:80px">Status</th></tr></thead>
      <tbody>
        {% for pg in pages %}
        <tr>
          <td>{{ pg.type }}</td>
          <td><code>{{ pg.url }}</code></td>
          <td>{{ pg.status }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </section>
  {% endif %}

  <footer>
    Audit generated {{ generated_at }}{% if generator %} by {{ generator }}{% endif %}.<br>
    Findings are limited to what could be observed from publicly accessible pages at that time.
    No performance, ranking, backlink or revenue claims are made beyond the measurements shown above.
  </footer>
</div>
</body>
</html>
"""

_TIER_COLORS = {
    "Very High": ("#fdecec", "#b02a2a"),
    "High": ("#fdf0e6", "#a85a08"),
    "Good": ("#eef2ff", "#3b4fb8"),
    "Moderate": ("#eef6f5", "#2b6b64"),
    "Low": ("#eef0f6", "#5b6478"),
}


def _dial_color(score: Optional[int]) -> str:
    if score is None:
        return "#c8cddb"
    if score >= 75:
        return "#d64545"
    if score >= 60:
        return "#e8913a"
    if score >= 40:
        return "#4c6ef5"
    return "#3f7d58"


def _band(score: Optional[int]) -> Dict[str, str]:
    """Higher-is-better colour band for the premium scorecard (0-100)."""
    if score is None:
        return {"key": "unknown", "label": "Not measured", "fg": "#5b6478"}
    if score >= 85:
        return {"key": "green", "label": "Good", "fg": "#2f7d54"}
    if score >= 70:
        return {"key": "yellow", "label": "Fair", "fg": "#9c7a0a"}
    if score >= 50:
        return {"key": "orange", "label": "Needs work", "fg": "#b3620c"}
    return {"key": "red", "label": "Poor", "fg": "#c53434"}


def _fmt_bool(v: Any, yes: str = "Yes", no: str = "No", unknown: str = "Not measured") -> str:
    if v is True:
        return yes
    if v is False:
        return no
    return unknown


def _evidence_lines(ev: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    if not isinstance(ev, dict):
        return out
    for key, val in ev.items():
        if val in (None, "", [], {}):
            continue
        label = key.replace("_", " ")
        if isinstance(val, list):
            items = []
            for v in val[:4]:
                if isinstance(v, dict):
                    items.append(v.get("url") or v.get("title") or str(v))
                else:
                    items.append(str(v))
            out.append(f"{label}: " + ", ".join(str(i)[:110] for i in items))
        elif isinstance(val, dict):
            continue
        else:
            out.append(f"{label}: {str(val)[:180]}")
        if len(out) >= 4:
            break
    return out


def _slugify(text: str, fallback: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", (text or "")).strip("-").lower()
    return (s[:60] or fallback)


def _finding_row(f: Finding) -> Dict[str, Any]:
    cat = audit_category_of(f)
    sev = f.severity if f.severity in SEVERITY_ORDER else "low"
    return {
        "code": f.code,
        "category": cat,
        "category_label": AUDIT_CATEGORY_LABELS.get(cat, cat.title()),
        "severity": sev,
        "severity_label": SEVERITY_LABEL.get(sev, "Note"),
        "title": f.title,
        "detail": f.detail,
        "evidence_lines": _evidence_lines(f.evidence),
        "recommendation": f.recommendation,
        "why_it_matters": AUDIT_CATEGORY_WHY.get(cat, ""),
        "priority": priority_for(f),
        "deduction": f.deduction,
    }


def _build_findings_context(
    legacy_findings: List[Finding], extra_findings: List[Finding]
) -> Dict[str, Any]:
    rows = [_finding_row(f) for f in list(legacy_findings) + list(extra_findings)]
    rows.sort(key=lambda r: (SEVERITY_ORDER.get(r["severity"], 2), -r["deduction"]))

    return {
        "all": rows,
        "critical": [r for r in rows if r["severity"] == "high"],
        "high": [r for r in rows if r["severity"] == "medium"],
        "warnings": [r for r in rows if r["severity"] == "low"],
        "action_plan": [r for r in rows if r["priority"] in ("P1", "P2")][:10],
    }


def _executive_summary(scorecard: Dict[str, Any], findings_ctx: Dict[str, Any]) -> str:
    if not scorecard:
        return ""
    pf = scorecard.get("pass_fail", {})
    parts = [
        f"This audit measured {pf.get('total_checked', 0)} checks across technical SEO, on-page "
        f"SEO, off-page/authority signals, performance, accessibility, security, UX and conversion."
    ]
    overall = scorecard.get("overall_score")
    if overall is not None:
        parts.append(
            f"The overall score is {overall}/100, with {pf.get('passed_count', 0)} of "
            f"{pf.get('total_checked', 0)} checks passing."
        )
    crit = len(findings_ctx["critical"])
    high = len(findings_ctx["high"])
    if crit:
        parts.append(f"{crit} critical issue{'s' if crit != 1 else ''} should be addressed first.")
    elif high:
        parts.append(
            f"No critical issues were found; {high} high-priority issue{'s' if high != 1 else ''} remain."
        )
    else:
        parts.append("No critical or high-priority issues were found in the checks this audit performs.")
    return " ".join(parts)


def render_report(
    *,
    business: Dict[str, Any],
    audit: Dict[str, Any],
    problems: List[Dict[str, Any]],
    recommendations: List[Dict[str, Any]],
    explanation: List[Dict[str, Any]],
    contacts: List[Dict[str, Any]],
    pages: List[Dict[str, Any]],
    generator: str = "",
    scorecard: Optional[Dict[str, Any]] = None,
    legacy_findings: Optional[List[Finding]] = None,
    extra_findings: Optional[List[Finding]] = None,
    extra_facts: Optional[Dict[str, Any]] = None,
) -> str:
    rec_by_code = {r.get("problem_code"): r.get("recommendation", "") for r in recommendations}
    enriched = []
    for p in problems:
        item = dict(p)
        item["recommendation"] = rec_by_code.get(p.get("code"), "")
        item["evidence_lines"] = _evidence_lines(p.get("evidence") or {})
        enriched.append(item)

    tier_bg, tier_fg = _TIER_COLORS.get(audit.get("opportunity_tier", ""), ("#eef0f6", "#5b6478"))

    tech = audit.get("technical") or {}
    mob = audit.get("mobile") or {}
    conv = audit.get("conversion") or {}
    perf = tech.get("pagespeed") or {}

    measured: List[Dict[str, str]] = []

    def add(label: str, value: Any) -> None:
        measured.append({"label": label, "value": "—" if value in (None, "") else str(value)})

    add("HTTP status", tech.get("http_status"))
    add("Served over HTTPS", _fmt_bool(tech.get("is_https")))
    add("Homepage response time", f"{tech['response_ms']} ms" if tech.get("response_ms") is not None else None)
    add("Pages crawled", tech.get("pages_crawled"))
    add("Mobile viewport tag", _fmt_bool(mob.get("has_viewport"), "Present", "Missing"))
    add("Tap-to-call on homepage", _fmt_bool(mob.get("tap_to_call_on_homepage"), "Present", "Not found"))
    add("Contact form detected", _fmt_bool(conv.get("has_contact_form"), "Yes", "Not found"))
    add("Booking option detected", _fmt_bool(conv.get("has_booking_cta"), "Yes", "Not found"))
    add("Page title", tech.get("title") or "Missing")
    add("Meta description", (tech.get("meta_description") or "Missing")[:160])
    add("H1 headings", tech.get("h1_count"))
    add("XML sitemap", _fmt_bool(tech.get("sitemap_found"), "Found", "Not found"))
    if tech.get("alt_coverage") is not None:
        add("Image alt coverage", f"{int(tech['alt_coverage'] * 100)}% of {tech.get('images_total', 0)} images")
    if tech.get("links_checked"):
        add("Internal links checked", f"{tech['links_checked']} ({len(tech.get('broken_links') or [])} broken)")
    if perf.get("measured"):
        add("Google PageSpeed", f"{perf.get('performance_score')}/100 ({perf.get('strategy')})")
        if perf.get("lcp_s") is not None:
            add("Largest Contentful Paint", f"{perf['lcp_s']} s")

    method_note = (
        "Technical and conversion findings come from server-side HTTP requests and HTML parsing. "
        "Mobile findings are derived from the page's own markup and inline CSS, not from a rendered "
        "phone browser; external stylesheets were not downloaded. "
    )
    if perf.get("measured"):
        method_note += "Performance figures come from the Google PageSpeed Insights API."
    else:
        method_note += (
            "Response time is a single server-side measurement from the machine that ran this audit, "
            "not a full performance profile."
        )

    findings_ctx = _build_findings_context(legacy_findings or [], extra_findings or [])

    category_sections: List[Dict[str, Any]] = []
    if scorecard:
        by_cat: Dict[str, List[Dict[str, Any]]] = {c: [] for c in AUDIT_CATEGORIES}
        for row in findings_ctx["all"]:
            by_cat.setdefault(row["category"], []).append(row)
        for c in AUDIT_CATEGORIES:
            category_sections.append({
                "key": c,
                "label": AUDIT_CATEGORY_LABELS.get(c, c.title()),
                "findings": by_cat.get(c, []),
            })

    scorecard_ctx: Dict[str, Any] = {}
    if scorecard:
        cats = []
        for row in scorecard.get("categories", []):
            cats.append({**row, "band": _band(row.get("health"))})
        scorecard_ctx = {**scorecard, "categories": cats}

    tmpl = _env.from_string(TEMPLATE)
    return tmpl.render(
        business=business,
        audit=audit,
        problems=enriched,
        explanation=explanation,
        contacts=contacts,
        pages=pages,
        measured=measured,
        method_note=method_note,
        dial_color=_dial_color(audit.get("score")),
        tier_bg=tier_bg,
        tier_fg=tier_fg,
        generated_at=dt.datetime.now().strftime("%d %b %Y at %H:%M"),
        generator=generator,
        scorecard=scorecard_ctx,
        findings=findings_ctx,
        category_sections=category_sections,
        executive_summary=_executive_summary(scorecard_ctx, findings_ctx),
    )


def write_report(job_id: int, business_id: int, business_name: str, html: str) -> str:
    folder = REPORT_DIR / f"job_{job_id}"
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{business_id:06d}-{_slugify(business_name, 'business')}.html"
    path = folder / filename
    path.write_text(html, encoding="utf-8")
    return str(path)
