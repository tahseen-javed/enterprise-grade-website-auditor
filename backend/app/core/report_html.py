"""
Premium, printable HTML audit report.

Self-contained and rendered through Jinja2 with autoescaping on, so nothing
scraped from a third-party site can inject markup into the report.

Structure (each numbered section below starts a fresh printed page):
  1. Cover + executive summary: overall score, category scorecard grid,
     what's working / top problems / biggest opportunities / business
     impact / next steps, and the Top 5 priorities.
  2. Visual scorecard: score gauge, category comparison, issues-by-severity,
     checks-by-status and priority-distribution charts (inline SVG, no JS).
  3+. One page per audit category (01 Technical SEO ... 08 UX & Conversion),
     each with its score, what's good, what needs improvement (every finding
     as What we found / Why it matters / How to fix / Evidence), and a
     Not Applicable / Not Verified banner where relevant - never a fabricated
     score for something that was not actually measured.

Every number traces back to a Finding produced by audit_checks.py, or to a
check explicitly marked Not Verified/Not Applicable. Nothing is invented to
fill a section; empty or unmeasurable sections say so plainly.
"""

from __future__ import annotations

import datetime as dt
import math
import re
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

# ============================================================================
# TEMPLATE
# ============================================================================

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Website Audit — {{ business.name }}</title>
<style>
  :root{
    --bg:#eef0f6; --surface:#ffffff; --ink:#131722; --ink-2:#333b4d; --muted:#5b6478; --line:#e4e7ef;
    --brand:#3b5bdb; --brand-soft:#eef2ff; --brand-2:#5f3dc4;
    --high:#c53434; --high-bg:#fdecec; --med:#9c7a0a; --med-bg:#fdf8e3;
    --low:#3f7d58; --low-bg:#ecf6f0; --shadow:0 1px 2px rgba(16,24,40,.06),0 8px 24px rgba(16,24,40,.06);
    --green:#2f7d54; --green-bg:#ecf6f0; --yellow:#9c7a0a; --yellow-bg:#fdf8e3;
    --orange:#b3620c; --orange-bg:#fdf1e3; --red:#c53434; --red-bg:#fdecec;
    --gray:#7b8299; --gray-bg:#eef0f6;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.62 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    -webkit-font-smoothing:antialiased;}
  .doc{max-width:1080px;margin:0 auto;padding:28px 20px 64px}
  .card{background:var(--surface);border:1px solid var(--line);border-radius:16px;
    padding:28px;margin-bottom:18px;box-shadow:var(--shadow)}
  .page{break-before:page;padding-top:2px}
  .page:first-child{break-before:auto}
  .page-marker{display:flex;align-items:center;gap:10px;margin:34px 0 14px;color:var(--muted);
    font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase}
  .page-marker::after{content:"";flex:1;height:1px;background:var(--line)}
  .page:first-child .page-marker{margin-top:0}

  header.cover{background:linear-gradient(135deg,#1b2138 0%,#2d3560 55%,#3b3f7a 100%);color:#fff;
    border:none;position:relative;overflow:hidden}
  header.cover::after{content:"";position:absolute;inset:0;
    background:radial-gradient(600px 260px at 90% -10%, rgba(255,255,255,.10), transparent 60%)}
  header.cover .top{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;
    position:relative}
  header.cover .eyebrow{font-size:11px;letter-spacing:.16em;text-transform:uppercase;opacity:.72;
    margin:0 0 10px;font-weight:700}
  header.cover h1{margin:0 0 8px;font-size:30px;line-height:1.2;letter-spacing:-.02em}
  header.cover .sub{opacity:.85;font-size:14px;margin:0;line-height:1.7}
  header.cover .sub a{color:#b7c6ff}
  header.cover .meta{display:flex;flex-direction:column;gap:2px;text-align:right;font-size:12.5px;
    opacity:.85;white-space:nowrap}
  header.cover .badge-report{display:inline-flex;align-items:center;gap:7px;background:rgba(255,255,255,.12);
    border:1px solid rgba(255,255,255,.22);border-radius:99px;padding:6px 14px;font-size:11.5px;
    font-weight:600;letter-spacing:.03em;margin-top:14px}

  h2{font-size:16.5px;margin:0 0 16px;letter-spacing:-.01em;display:flex;align-items:center;gap:9px}
  h2 .count{color:var(--muted);font-weight:400;font-size:13px}
  h3{font-size:14.5px;margin:0}
  .lede{font-size:15.5px;color:var(--ink-2);margin:0 0 4px;line-height:1.7}
  .section-num{width:30px;height:30px;border-radius:9px;background:var(--brand);color:#fff;
    display:grid;place-items:center;font-weight:700;font-size:13px;flex:0 0 auto}
  .section-title{display:flex;align-items:center;gap:12px;margin-bottom:6px}
  .section-title h2{margin:0}
  .section-sub{color:var(--muted);font-size:13px;margin:0 0 20px 42px}

  .scoregrid{display:grid;grid-template-columns:auto 1fr;gap:30px;align-items:center}
  @media(max-width:640px){.scoregrid{grid-template-columns:1fr;gap:18px;text-align:center}}
  .dial .num{font-size:34px;font-weight:700;letter-spacing:-.03em;line-height:1}

  .exec-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-top:18px}
  @media(max-width:760px){.exec-grid{grid-template-columns:1fr}}
  .exec-block{border:1px solid var(--line);border-radius:12px;padding:16px 18px;background:#fbfbfe}
  .exec-block h4{margin:0 0 10px;font-size:12px;text-transform:uppercase;letter-spacing:.07em;
    color:var(--muted);display:flex;align-items:center;gap:7px}
  .exec-block ul{margin:0;padding-left:18px;line-height:1.8;font-size:13.5px;color:var(--ink-2)}
  .exec-block p{margin:0;font-size:13.5px;color:var(--ink-2);line-height:1.7}
  .exec-block.impact{grid-column:1/-1;background:var(--brand-soft);border-color:#dbe2ff}
  .exec-block.impact h4{color:var(--brand)}

  .catgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
  .catrow{border:1px solid var(--line);border-radius:12px;padding:14px 16px;background:#fcfcfe;
    display:flex;flex-direction:column;gap:8px}
  .catrow .top{display:flex;justify-content:space-between;align-items:center;gap:8px}
  .catrow .name{font-size:12.5px;font-weight:600}
  .catrow .score{font-size:22px;font-weight:700;letter-spacing:-.02em}
  .track{height:8px;background:#eef0f6;border-radius:99px;overflow:hidden}
  .fill{height:100%;border-radius:99px}
  .band{font-size:10px;font-weight:700;padding:3px 9px;border-radius:99px;letter-spacing:.03em;
    white-space:nowrap}
  .band.green{background:var(--green-bg);color:var(--green)}
  .band.yellow{background:var(--yellow-bg);color:var(--yellow)}
  .band.orange{background:var(--orange-bg);color:var(--orange)}
  .band.red{background:var(--red-bg);color:var(--red)}
  .band.gray{background:var(--gray-bg);color:var(--gray)}

  .prio-list{display:flex;flex-direction:column;gap:12px}
  .prio-card{display:grid;grid-template-columns:38px 1fr;gap:14px;border:1px solid var(--line);
    border-radius:12px;padding:14px 16px;background:#fcfcfe}
  .prio-num{width:30px;height:30px;border-radius:50%;background:var(--brand-soft);color:var(--brand);
    display:grid;place-items:center;font-weight:700;font-size:13px}
  .prio-card .head{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;margin-bottom:5px}
  .prio-card .title{font-size:14px;font-weight:600}
  .prio-card .meta{font-size:12.5px;color:var(--muted);margin:0 0 6px}
  .prio-card .action{font-size:13px;color:var(--ink-2)}
  .prio-card .action b{color:var(--brand)}

  .sev{font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
    padding:3px 9px;border-radius:6px;white-space:nowrap}
  .sev.high{background:var(--high-bg);color:var(--high)}
  .sev.medium{background:var(--med-bg);color:var(--med)}
  .sev.low{background:var(--low-bg);color:var(--low)}
  .pri{font-size:10px;font-weight:700;padding:3px 8px;border-radius:6px;background:#eef0f6;color:var(--muted)}
  .cat-chip{font-size:10px;font-weight:600;padding:3px 9px;border-radius:6px;background:var(--brand-soft);color:var(--brand)}
  .status-chip{font-size:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
    padding:4px 10px;border-radius:6px;white-space:nowrap}

  .chartrow{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:18px;
    text-align:center}
  .chartcard{display:flex;flex-direction:column;align-items:center;gap:10px}
  .chartcard .title{font-size:12.5px;font-weight:600;color:var(--ink-2)}
  .legend{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;font-size:11.5px;color:var(--muted)}
  .legend .dot{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:5px;vertical-align:-1px}

  .finding{border:1px solid var(--line);border-left-width:4px;border-radius:12px;
    padding:17px 19px;margin-bottom:13px;background:#fcfcfe}
  .finding.high{border-left-color:var(--high)}
  .finding.medium{border-left-color:var(--med)}
  .finding.low{border-left-color:var(--low)}
  .finding h3{margin:0 0 10px;font-size:15px;display:flex;gap:9px;align-items:baseline;flex-wrap:wrap}
  .finding .field{margin:0 0 9px}
  .finding .field:last-child{margin-bottom:0}
  .finding .flabel{font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
    color:var(--muted);margin:0 0 3px}
  .finding .fbody{margin:0;color:var(--ink-2);font-size:13.5px;line-height:1.65}
  .finding .fix{background:var(--brand-soft);border-radius:9px;padding:11px 13px}
  .finding .fix .fbody{color:#2b3a6b}
  ul.evidence{margin:4px 0 0;padding-left:18px;font-size:12px;color:var(--muted)}

  .checklist{display:flex;flex-direction:column;gap:7px}
  .check-row{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:9px;
    background:#fcfcfe;border:1px solid var(--line);font-size:13px}
  .check-row .label{flex:1;color:var(--ink-2)}
  .check-row .icon{width:18px;height:18px;border-radius:50%;display:grid;place-items:center;
    font-size:11px;font-weight:700;color:#fff;flex:0 0 auto}

  .disclosure{background:#f8f9fc;border:1px dashed #ccd3e0;border-radius:10px;
    padding:13px 15px;font-size:12.5px;color:var(--muted);margin-top:12px}
  .na-banner{border:1px solid var(--line);background:#f8f9fc;border-radius:12px;padding:20px;
    text-align:center;color:var(--muted);font-size:13.5px;line-height:1.7}
  .na-banner b{color:var(--ink-2)}

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
  .meta-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}
  .meta-grid div{font-size:13px}
  .meta-grid dt{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.07em;margin-bottom:3px}
  .meta-grid dd{margin:0;font-weight:500;word-break:break-word}
  .kpirow{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px}
  .kpi{border:1px solid var(--line);border-radius:12px;padding:14px 16px;background:#fcfcfe;text-align:center}
  .kpi .n{font-size:24px;font-weight:700;letter-spacing:-.02em}
  .kpi .l{font-size:10.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-top:3px}

  footer.doc-footer{text-align:center;color:var(--muted);font-size:12px;margin-top:30px;line-height:1.8;
    padding-top:20px;border-top:1px solid var(--line)}

  @media print{
    body{background:#fff}
    .card{box-shadow:none;border:1px solid #e4e7ef}
    .doc{max-width:none;padding:0}
  }
  @page{
    margin:16mm 14mm 18mm;
    @bottom-center{ content:"Page " counter(page) " of " counter(pages); font-size:9px; color:#8a90a3; }
    @top-right{ content:"{{ business.name|e }} — Website Audit"; font-size:8.5px; color:#a3a8b8; }
  }
</style>
</head>
<body>
<div class="doc">

  <!-- ============================== PAGE 1 ============================== -->
  <div class="page" id="page-1">
  <header class="card cover">
    <div class="top">
      <div>
        <p class="eyebrow">Website Audit Report</p>
        <h1>{{ business.name }}</h1>
        <p class="sub">
          {% if audit.website %}<a href="{{ audit.website }}" rel="noopener nofollow">{{ audit.website }}</a>{% else %}No website found{% endif %}
          {% if business.location %}<br>{{ business.location }}{% endif %}
          {% if business.category %} · {{ business.category }}{% endif %}
        </p>
        <span class="badge-report">Prepared {{ generated_at }}{% if generator %} by {{ generator }}{% endif %}</span>
      </div>
      <div class="meta">
        <div>Audit date</div>
        <div style="font-weight:600;font-size:14px;color:#fff">{{ generated_at }}</div>
      </div>
    </div>
  </header>

  {% if scorecard %}
  <section class="card">
    <div class="scoregrid">
      {{ gauge_overall|safe }}
      <div>
        <div class="row" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
          <span class="band {{ overall_band.key }}" style="font-size:12px;padding:5px 12px">{{ overall_band.label }}</span>
          <strong style="font-size:15px">Overall score {{ scorecard.overall_score }}/100</strong>
        </div>
        <p class="lede">{{ executive_summary.headline }}</p>
        <div class="kpirow" style="margin-top:14px">
          <div class="kpi"><div class="n" style="color:var(--green)">{{ checks.passed_count }}</div><div class="l">Passed</div></div>
          <div class="kpi"><div class="n" style="color:var(--yellow)">{{ checks.warning_count }}</div><div class="l">Warnings</div></div>
          <div class="kpi"><div class="n" style="color:var(--red)">{{ checks.failed_count }}</div><div class="l">Critical</div></div>
          <div class="kpi"><div class="n" style="color:var(--gray)">{{ checks.not_verified_count }}</div><div class="l">Not verified</div></div>
          <div class="kpi"><div class="n" style="color:var(--gray)">{{ checks.not_applicable_count }}</div><div class="l">Not applicable</div></div>
        </div>
      </div>
    </div>
  </section>

  <section class="card">
    <h2>Category scores</h2>
    <div class="catgrid">
      {% for c in scorecard.categories %}
      <div class="catrow">
        <div class="top">
          <span class="name">{{ c.label }}</span>
          <span class="band {{ c.band.key }}">{{ c.band.label }}</span>
        </div>
        {% if c.applicable %}
        <div class="score" style="color:{{ c.band.fg }}">{{ c.score }}<span style="font-size:13px;color:var(--muted)">/100</span></div>
        <div class="track"><span class="fill {{ c.band.key }}" style="width:{{ c.score }}%;background:{{ c.band.fg }}"></span></div>
        {% else %}
        <div class="score" style="color:var(--gray)">N/A</div>
        <div class="track"><span class="fill gray" style="width:100%;background:#d7dbe6"></span></div>
        {% endif %}
      </div>
      {% endfor %}
    </div>
  </section>

  <section class="card">
    <h2>Executive summary</h2>
    <div class="exec-grid">
      <div class="exec-block">
        <h4>✓ What's working well</h4>
        {% if executive_summary.whats_working %}
        <ul>{% for w in executive_summary.whats_working %}<li>{{ w }}</li>{% endfor %}</ul>
        {% else %}<p>No category currently scores in the "Good" range.</p>{% endif %}
      </div>
      <div class="exec-block">
        <h4>! Top problems</h4>
        {% if executive_summary.top_problems %}
        <ul>{% for p in executive_summary.top_problems %}<li>{{ p }}</li>{% endfor %}</ul>
        {% else %}<p>No significant problems were found.</p>{% endif %}
      </div>
      <div class="exec-block">
        <h4>↑ Biggest opportunities</h4>
        {% if executive_summary.biggest_opportunities %}
        <ul>{% for o in executive_summary.biggest_opportunities %}<li>{{ o }}</li>{% endfor %}</ul>
        {% else %}<p>No category currently scores below 70.</p>{% endif %}
      </div>
      <div class="exec-block">
        <h4>→ Recommended next steps</h4>
        {% if executive_summary.next_steps %}
        <ul>{% for n in executive_summary.next_steps %}<li>{{ n }}</li>{% endfor %}</ul>
        {% else %}<p>No specific actions are outstanding.</p>{% endif %}
      </div>
      <div class="exec-block impact">
        <h4>Business impact</h4>
        <p>{{ executive_summary.business_impact }}</p>
      </div>
    </div>
  </section>

  <section class="card">
    <h2>Top 5 priorities</h2>
    {% if priorities %}
    <div class="prio-list">
      {% for p in priorities %}
      <div class="prio-card">
        <div class="prio-num">{{ p.rank }}</div>
        <div>
          <div class="head">
            <span class="sev {{ p.severity }}">{{ p.severity_label }}</span>
            <span class="pri">{{ p.priority }}</span>
            <span class="cat-chip">{{ p.category_label }}</span>
            <span class="title">{{ p.title }}</span>
          </div>
          <p class="meta">{{ p.detail }}</p>
          {% if p.recommendation %}<p class="action"><b>Recommended action:</b> {{ p.recommendation }}</p>{% endif %}
        </div>
      </div>
      {% endfor %}
    </div>
    {% else %}
    <p style="margin:0;color:var(--muted)">No priority issues were detected within the checks this audit performs.</p>
    {% endif %}
  </section>
  {% endif %}
  </div>

  {% if scorecard %}
  <!-- ============================== PAGE 2 ============================== -->
  <div class="page" id="page-2">
  <div class="page-marker">Visual scorecard</div>
  <section class="card">
    <h2>At a glance</h2>
    <div class="chartrow">
      <div class="chartcard">
        <div class="title">Overall score</div>
        {{ gauge_overall_sm|safe }}
      </div>
      <div class="chartcard">
        <div class="title">Issues by severity</div>
        {{ donut_severity|safe }}
        <div class="legend">
          <span><span class="dot" style="background:var(--high)"></span>Critical {{ scorecard.severity_counts.high }}</span>
          <span><span class="dot" style="background:var(--med)"></span>High {{ scorecard.severity_counts.medium }}</span>
          <span><span class="dot" style="background:var(--low)"></span>Warning {{ scorecard.severity_counts.low }}</span>
        </div>
      </div>
      <div class="chartcard">
        <div class="title">Checks by status</div>
        {{ donut_status|safe }}
        <div class="legend">
          <span><span class="dot" style="background:#2f7d54"></span>Passed {{ checks.passed_count }}</span>
          <span><span class="dot" style="background:#9c7a0a"></span>Warning {{ checks.warning_count }}</span>
          <span><span class="dot" style="background:#c53434"></span>Critical {{ checks.failed_count }}</span>
          <span><span class="dot" style="background:#a8afc0"></span>N/V or N/A {{ checks.not_verified_count + checks.not_applicable_count }}</span>
        </div>
      </div>
      <div class="chartcard">
        <div class="title">Priority distribution</div>
        {{ donut_priority|safe }}
        <div class="legend">
          <span><span class="dot" style="background:#c53434"></span>P1 {{ priority_counts.P1 }}</span>
          <span><span class="dot" style="background:#e8913a"></span>P2 {{ priority_counts.P2 }}</span>
          <span><span class="dot" style="background:#4c6ef5"></span>P3 {{ priority_counts.P3 }}</span>
        </div>
      </div>
    </div>
  </section>

  <section class="card">
    <h2>Category comparison <span class="count">— higher is better</span></h2>
    <div class="bars" style="display:flex;flex-direction:column;gap:12px">
      {% for c in scorecard.categories %}
      <div class="bar-row" style="display:grid;grid-template-columns:150px 1fr 50px;gap:12px;align-items:center;font-size:13px">
        <span class="name">{{ c.label }}</span>
        {% if c.applicable %}
        <div class="track"><span class="fill" style="width:{{ c.score }}%;background:{{ c.band.fg }}"></span></div>
        <span style="text-align:right;color:var(--muted);font-variant-numeric:tabular-nums">{{ c.score }}</span>
        {% else %}
        <div class="track"><span class="fill" style="width:100%;background:#e4e7ef"></span></div>
        <span style="text-align:right;color:var(--gray)">N/A</span>
        {% endif %}
      </div>
      {% endfor %}
    </div>
  </section>
  </div>
  {% endif %}

  <!-- ========================== DETAILED SECTIONS ========================= -->
  {% for cat in category_sections %}
  <div class="page" id="cat-{{ cat.key }}">
  <div class="page-marker">Detailed audit — {{ cat.number }} of {{ category_sections|length }}</div>
  <section class="card">
    <div class="section-title">
      <div class="section-num">{{ cat.number }}</div>
      <h2>{{ cat.label }}</h2>
      {% if cat.applicable %}
      <span class="band {{ cat.band.key }}" style="margin-left:auto">{{ cat.band.label }} — {{ cat.score }}/100</span>
      {% else %}
      <span class="band gray" style="margin-left:auto">Not Applicable</span>
      {% endif %}
    </div>
    <p class="section-sub">{{ cat.why_it_matters }}</p>

    {% if not cat.applicable %}
    <div class="na-banner">
      <b>Not applicable to this website.</b><br>{{ cat.not_applicable_reason }}
    </div>
    {% else %}

    {% if cat.passed_checks %}
    <div class="field" style="margin-bottom:18px">
      <div class="flabel" style="margin-bottom:8px">What's good — {{ cat.passed_checks|length }} check{{ 's' if cat.passed_checks|length != 1 else '' }} passed</div>
      <div class="checklist">
        {% for chk in cat.passed_checks %}
        <div class="check-row"><span class="icon" style="background:#2f7d54">✓</span><span class="label">{{ chk.label }}</span></div>
        {% endfor %}
      </div>
    </div>
    {% endif %}

    {% if cat.not_verified_checks %}
    <div class="field" style="margin-bottom:18px">
      <div class="flabel" style="margin-bottom:8px">Not verified</div>
      <div class="checklist">
        {% for chk in cat.not_verified_checks %}
        <div class="check-row"><span class="icon" style="background:#7b8299">?</span><span class="label">{{ chk.label }} — {{ chk.detail }}</span></div>
        {% endfor %}
      </div>
    </div>
    {% endif %}

    {% if cat.findings %}
    <div class="flabel" style="margin:6px 0 10px">What needs improvement — {{ cat.findings|length }} finding{{ 's' if cat.findings|length != 1 else '' }}</div>
    {% for p in cat.findings %}
    <article class="finding {{ p.severity }}">
      <h3>
        <span class="sev {{ p.severity }}">{{ p.severity_label }}</span>
        <span class="pri">{{ p.priority }}</span>
        {{ p.title }}
      </h3>
      <div class="field">
        <div class="flabel">What we found</div>
        <p class="fbody">{{ p.detail }}</p>
      </div>
      {% if p.why_it_matters %}
      <div class="field">
        <div class="flabel">Why it matters</div>
        <p class="fbody">{{ p.why_it_matters }}</p>
      </div>
      {% endif %}
      {% if p.recommendation %}
      <div class="field fix">
        <div class="flabel">How to fix</div>
        <p class="fbody">{{ p.recommendation }}</p>
      </div>
      {% endif %}
      {% if p.evidence_lines %}
      <ul class="evidence">{% for line in p.evidence_lines %}<li>{{ line }}</li>{% endfor %}</ul>
      {% endif %}
    </article>
    {% endfor %}
    {% else %}
    <p style="margin:0;color:var(--muted)">No evidence-backed issues were detected in this category.</p>
    {% endif %}

    {% if cat.key == 'offpage' %}
    <div class="disclosure">
      <b>Not verified:</b> backlink count, referring domains and domain-authority-style scores
      require a paid third-party index (e.g. Ahrefs, Moz, Majestic, SEMrush). None is configured for
      this audit, so none of that is estimated or fabricated here.
    </div>
    {% endif %}
    {% if cat.key == 'accessibility' %}
    <div class="disclosure">
      <b>Not verified:</b> colour contrast requires a rendered page with computed styles and cannot
      be measured reliably from static HTML/CSS, so it is reported as not verified rather than guessed.
    </div>
    {% endif %}
    {% endif %}
  </section>
  </div>
  {% endfor %}

  {% if not scorecard %}
  <div class="page">
  <section class="card">
    <div class="scoregrid">
      <div style="width:132px;height:132px;border-radius:50%;display:grid;place-items:center;
        background:conic-gradient({{ dial_color }} calc({{ audit.score or 0 }}*1%), #e9ecf4 0)">
        <div style="width:104px;height:104px;border-radius:50%;background:var(--surface);display:grid;place-items:center;text-align:center">
          <div class="num">{{ audit.score if audit.score is not none else '—' }}</div>
        </div>
      </div>
      <div>
        <p style="margin:0 0 12px">
          <span class="band gray" style="font-size:13px">{{ audit.opportunity_tier or 'Not scored' }}</span>
        </p>
        <p class="note" style="margin-top:0;border-top:none;padding-top:0">
          {{ audit.audit_error or 'This business could not be fully audited. See below for what was checked.' }}
        </p>
      </div>
    </div>
  </section>

  {% if problems %}
  <section class="card">
    <h2>Detected problems <span class="count">— {{ problems|length }} found</span></h2>
    {% for p in problems %}
    <article class="finding {{ p.severity }}">
      <h3><span class="sev {{ p.severity }}">{{ p.severity }}</span>{{ p.title }}</h3>
      <div class="field"><div class="flabel">What we found</div><p class="fbody">{{ p.detail }}</p></div>
      {% if p.recommendation %}<div class="field fix"><div class="flabel">How to fix</div><p class="fbody">{{ p.recommendation }}</p></div>{% endif %}
      {% if p.evidence_lines %}<ul class="evidence">{% for line in p.evidence_lines %}<li>{{ line }}</li>{% endfor %}</ul>{% endif %}
    </article>
    {% endfor %}
  </section>
  {% else %}
  <section class="card">
    <h2>Detected problems</h2>
    <p style="margin:0;color:var(--muted)">
      No evidence-backed problems were detected within the checks this audit performs.
      No issues have been invented to fill this section.
    </p>
  </section>
  {% endif %}
  </div>
  {% endif %}

  <!-- ============================ APPENDIX ============================ -->
  <div class="page">
  <div class="page-marker">Appendix</div>
  <section class="card">
    <h2>What was measured</h2>
    <table>
      <tbody>
        {% for row in measured %}
        <tr><th style="width:42%">{{ row.label }}</th><td>{{ row.value }}</td></tr>
        {% endfor %}
      </tbody>
    </table>
    <p class="note">{{ method_note }}</p>
  </section>

  <section class="card">
    <h2>Contact options found</h2>
    <div class="meta-grid">
      {% for c in contacts %}
      <div><dt>{{ c.label }}</dt><dd>{{ c.value }}{% if c.status %} <span class="pill {{ c.pill }}">{{ c.status }}</span>{% endif %}</dd></div>
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
        <tr><td>{{ pg.type }}</td><td><code>{{ pg.url }}</code></td><td>{{ pg.status }}</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </section>
  {% endif %}

  <footer class="doc-footer">
    Audit generated {{ generated_at }}{% if generator %} by {{ generator }}{% endif %}.<br>
    Findings are limited to what could be observed from publicly accessible pages at that time.
    No performance, ranking, backlink, review-count or revenue claims are made beyond the
    measurements shown in this report. Checks that could not be measured are labelled
    "Not verified"; categories that do not apply to this site are labelled "Not applicable" -
    neither is ever scored as if it had passed or failed.
  </footer>
  </div>

</div>
</body>
</html>
"""

# ============================================================================
# Small inline-SVG chart helpers - no external JS/CSS libraries, so the
# report stays a single self-contained file suitable for printing to PDF.
# ============================================================================


def _svg_gauge(score: Optional[int], size: int = 176, color: str = "#3b5bdb") -> str:
    r = size / 2 - 15
    cx = cy = size / 2
    circumference = 2 * math.pi * r
    pct = 0 if score is None else max(0, min(100, score))
    dash = circumference * pct / 100
    label = "—" if score is None else str(score)
    font1 = round(size * 0.20)
    font2 = round(size * 0.08)
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img" aria-label="Score {label} out of 100">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#e9ecf4" stroke-width="15"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="15" '
        f'stroke-dasharray="{dash:.1f} {circumference:.1f}" stroke-linecap="round" '
        f'transform="rotate(-90 {cx} {cy})"/>'
        f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" font-size="{font1}" font-weight="700" '
        f'font-family="-apple-system,Segoe UI,Roboto,Arial,sans-serif" fill="#131722">{label}</text>'
        f'<text x="{cx}" y="{cy + 20}" text-anchor="middle" font-size="{font2}" '
        f'font-family="-apple-system,Segoe UI,Roboto,Arial,sans-serif" fill="#5b6478">/ 100</text>'
        f'</svg>'
    )


def _svg_donut(segments: List[Dict[str, Any]], size: int = 140) -> str:
    total = sum(max(0, s.get("value", 0)) for s in segments)
    r = size / 2 - 16
    cx = cy = size / 2
    circumference = 2 * math.pi * r
    if total <= 0:
        return (
            f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#e9ecf4" stroke-width="18"/>'
            f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" font-size="12" fill="#a8afc0" '
            f'font-family="-apple-system,Segoe UI,Roboto,Arial,sans-serif">none</text></svg>'
        )
    offset = 0.0
    arcs = []
    for s in segments:
        v = max(0, s.get("value", 0))
        if v == 0:
            continue
        frac = v / total
        dash = circumference * frac
        arcs.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{s["color"]}" stroke-width="18" '
            f'stroke-dasharray="{dash:.2f} {circumference:.2f}" stroke-dashoffset="{-offset:.2f}" '
            f'transform="rotate(-90 {cx} {cy})"/>'
        )
        offset += dash
    body = "".join(arcs)
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
        f'{body}'
        f'<text x="{cx}" y="{cy + 6}" text-anchor="middle" font-size="{round(size * 0.16)}" font-weight="700" '
        f'font-family="-apple-system,Segoe UI,Roboto,Arial,sans-serif" fill="#131722">{total}</text>'
        f'</svg>'
    )


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


def _band(score: Optional[int], applicable: bool = True) -> Dict[str, str]:
    """Higher-is-better colour band for the premium scorecard (0-100)."""
    if not applicable:
        return {"key": "gray", "label": "Not Applicable", "fg": "#7b8299"}
    if score is None:
        return {"key": "gray", "label": "Not Verified", "fg": "#7b8299"}
    if score >= 85:
        return {"key": "green", "label": "Good", "fg": "#2f7d54"}
    if score >= 70:
        return {"key": "yellow", "label": "Needs Improvement", "fg": "#9c7a0a"}
    if score >= 50:
        return {"key": "orange", "label": "Important Issue", "fg": "#b3620c"}
    return {"key": "red", "label": "Critical Issue", "fg": "#c53434"}


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
    }


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
    priorities: Optional[List[Dict[str, Any]]] = None,
    executive_summary: Optional[Dict[str, Any]] = None,
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

    priorities_ctx = [
        {**p, "severity_label": SEVERITY_LABEL.get(p.get("severity", ""), "Note")}
        for p in (priorities or [])
    ]

    # ---- category sections (detailed pages) --------------------------------
    category_sections: List[Dict[str, Any]] = []
    if scorecard:
        by_cat: Dict[str, List[Dict[str, Any]]] = {c: [] for c in AUDIT_CATEGORIES}
        for row in findings_ctx["all"]:
            by_cat.setdefault(row["category"], []).append(row)

        checks_by_cat: Dict[str, List[Dict[str, Any]]] = {c: [] for c in AUDIT_CATEGORIES}
        for chk in (scorecard.get("checks") or {}).get("checks", []):
            checks_by_cat.setdefault(chk["category"], []).append(chk)

        cat_row_by_key = {c["category"]: c for c in scorecard.get("categories", [])}

        for i, c in enumerate(AUDIT_CATEGORIES):
            row = cat_row_by_key.get(c, {})
            applicable = row.get("applicable", True)
            score = row.get("score")
            checks_here = checks_by_cat.get(c, [])
            category_sections.append({
                "key": c,
                "number": f"{i + 1:02d}",
                "label": AUDIT_CATEGORY_LABELS.get(c, c.title()),
                "why_it_matters": AUDIT_CATEGORY_WHY.get(c, ""),
                "applicable": applicable,
                "not_applicable_reason": row.get("not_applicable_reason", ""),
                "score": score,
                "band": _band(score, applicable),
                "findings": by_cat.get(c, []),
                "passed_checks": [x for x in checks_here if x["status"] == "pass"],
                "not_verified_checks": [x for x in checks_here if x["status"] == "not_verified"],
            })

    scorecard_ctx: Dict[str, Any] = {}
    checks_ctx: Dict[str, Any] = {
        "passed_count": 0, "warning_count": 0, "failed_count": 0,
        "not_verified_count": 0, "not_applicable_count": 0, "total_checked": 0,
    }
    priority_counts = {"P1": 0, "P2": 0, "P3": 0}
    donut_severity = donut_status = donut_priority = ""
    gauge_overall = gauge_overall_sm = ""
    overall_band = _band(None)

    if scorecard:
        cats = []
        for row in scorecard.get("categories", []):
            cats.append({**row, "band": _band(row.get("score"), row.get("applicable", True))})
        scorecard_ctx = {**scorecard, "categories": cats}
        checks_ctx = scorecard.get("checks", checks_ctx)
        overall_band = _band(scorecard.get("overall_score"))

        for f in (list(legacy_findings or []) + list(extra_findings or [])):
            if f.deduction > 0:
                priority_counts[priority_for(f)] = priority_counts.get(priority_for(f), 0) + 1

        gauge_overall = _svg_gauge(scorecard.get("overall_score"), size=176, color=overall_band["fg"])
        gauge_overall_sm = _svg_gauge(scorecard.get("overall_score"), size=140, color=overall_band["fg"])
        donut_severity = _svg_donut([
            {"value": scorecard.get("severity_counts", {}).get("high", 0), "color": "#c53434"},
            {"value": scorecard.get("severity_counts", {}).get("medium", 0), "color": "#9c7a0a"},
            {"value": scorecard.get("severity_counts", {}).get("low", 0), "color": "#3f7d58"},
        ])
        donut_status = _svg_donut([
            {"value": checks_ctx.get("passed_count", 0), "color": "#2f7d54"},
            {"value": checks_ctx.get("warning_count", 0), "color": "#9c7a0a"},
            {"value": checks_ctx.get("failed_count", 0), "color": "#c53434"},
            {"value": checks_ctx.get("not_verified_count", 0) + checks_ctx.get("not_applicable_count", 0), "color": "#a8afc0"},
        ])
        donut_priority = _svg_donut([
            {"value": priority_counts.get("P1", 0), "color": "#c53434"},
            {"value": priority_counts.get("P2", 0), "color": "#e8913a"},
            {"value": priority_counts.get("P3", 0), "color": "#4c6ef5"},
        ])

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
        checks=checks_ctx,
        findings=findings_ctx,
        category_sections=category_sections,
        priorities=priorities_ctx,
        executive_summary=executive_summary or {},
        overall_band=overall_band,
        priority_counts=priority_counts,
        gauge_overall=gauge_overall,
        gauge_overall_sm=gauge_overall_sm,
        donut_severity=donut_severity,
        donut_status=donut_status,
        donut_priority=donut_priority,
    )


def write_report(job_id: int, business_id: int, business_name: str, html: str) -> str:
    folder = REPORT_DIR / f"job_{job_id}"
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{business_id:06d}-{_slugify(business_name, 'business')}.html"
    path = folder / filename
    path.write_text(html, encoding="utf-8")
    return str(path)
