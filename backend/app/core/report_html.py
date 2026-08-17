"""
Premium, printable HTML audit report.

Self-contained and rendered through Jinja2 with autoescaping on, so nothing
scraped from a third-party site can inject markup into the report.

Visual language: an enterprise/SaaS dark presentation - deep navy ground,
gradient score rings with a soft glow, large display numerals, status-graded
cards and inline-SVG charts. On paper it flips to an ink-friendly light
palette (see the `@media print` block) so the same document is both a
screen deliverable and a clean PDF.

Structure (each numbered section below starts a fresh printed page):
  1. Cover + executive summary: overall score ring, headline verdict, the
     issue/passed-check counters, the 8-category scorecard grid, and the
     Top 5 priorities.
  2. Visual analytics: category comparison, issues-by-severity,
     checks-by-status and priority-distribution charts (inline SVG, no JS).
  3. Verified signals: the raw measurements the audit actually took, with
     "Not Verified" / "Not Available" and the reason wherever it did not.
  4+. Issues & Recommendations - one page per audit category
     (01 Technical SEO ... 08 UX & Conversion), each with its score, the
     checks that passed, the checks that could not be verified, and every
     finding as What we found / Why it matters / How to fix / Evidence /
     Priority, plus a Not Applicable / Not Verified banner where relevant -
     never a fabricated score for something that was not actually measured.

Every number traces back to a Finding produced by audit_checks.py, or to a
check explicitly marked Not Verified/Not Applicable. Nothing is invented to
fill a section; empty or unmeasurable sections say so plainly. There are no
traffic, backlink, domain-authority, ranking or revenue figures anywhere in
this file, because the engine cannot measure them.
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
# Short, all-caps severity chips, matching the status vocabulary used across
# the report: CRITICAL / HIGH / MEDIUM / LOW / PASS / NOT VERIFIED / NOT APPLICABLE.
SEVERITY_BADGE = {"high": "CRITICAL", "medium": "HIGH", "low": "MEDIUM"}

# One glyph per premium category, purely decorative labelling of a real category.
CATEGORY_ICON = {
    "technical": "⚙",
    "onpage": "✎",
    "local_seo": "◎",
    "offpage": "⬈",
    "performance": "⚡",
    "accessibility": "☺",
    "security": "🛡",
    "ux_conversion": "◈",
}

# ============================================================================
# TEMPLATE
# ============================================================================

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Website Audit — {{ business.name }}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  :root{
    --void:#05070d; --navy:#0a0f1e; --card:#0e1526; --card-2:#111a30; --raise:rgba(255,255,255,.022);
    --line:rgba(148,178,255,.12); --line-bright:rgba(148,178,255,.26);
    --blue:#3b82f6; --cyan:#22d3ee; --violet:#8b5cf6;
    --green:#34d399; --amber:#fbbf24; --orange:#fb923c; --red:#fb5b6f; --slate:#7f8bad;
    --hi:#f4f7ff; --mid:#a9b4d0; --low:#6b7593;
    --font-display:'Space Grotesk','Segoe UI',system-ui,sans-serif;
    --font-body:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
    --font-mono:'JetBrains Mono','SF Mono',ui-monospace,Consolas,'Courier New',monospace;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html{-webkit-text-size-adjust:100%}
  body{
    background:
      radial-gradient(1200px 620px at 10% -12%, rgba(59,130,246,.16), transparent 60%),
      radial-gradient(1000px 520px at 100% 0%, rgba(34,211,238,.10), transparent 55%),
      radial-gradient(900px 560px at 50% 108%, rgba(139,92,246,.10), transparent 60%),
      var(--void);
    background-attachment:fixed;
    color:var(--hi); font-family:var(--font-body); font-size:15px; line-height:1.6;
    -webkit-font-smoothing:antialiased; padding:26px 20px 56px;
  }
  .doc{max-width:1320px;margin:0 auto;display:flex;flex-direction:column;gap:16px}
  .mono{font-family:var(--font-mono)}
  .display{font-family:var(--font-display)}
  a{color:var(--cyan)}

  /* ---------- shared surfaces ---------- */
  .card{
    background:linear-gradient(160deg, var(--card) 0%, var(--navy) 100%);
    border:1px solid var(--line); border-radius:18px; padding:24px 26px;
  }
  .page{break-before:page}
  .page:first-child{break-before:auto}
  .page{display:flex;flex-direction:column;gap:16px}

  .section-head{display:flex;align-items:baseline;justify-content:space-between;gap:14px;
    margin:12px 4px 0;flex-wrap:wrap}
  .section-title{font-family:var(--font-display);font-weight:700;font-size:20px;letter-spacing:-.01em;
    display:flex;align-items:center;gap:11px}
  .section-title .bar{width:4px;height:19px;border-radius:3px;
    background:linear-gradient(180deg,var(--cyan),var(--blue));flex:0 0 auto}
  .section-sub{font-family:var(--font-mono);font-size:11.5px;letter-spacing:.12em;
    text-transform:uppercase;color:var(--low)}

  .eyebrow{display:inline-flex;align-items:center;gap:8px;font-family:var(--font-mono);
    font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--cyan);width:fit-content;
    background:rgba(34,211,238,.08);border:1px solid rgba(34,211,238,.28);padding:5px 12px;border-radius:100px}
  .eyebrow .dot{width:6px;height:6px;border-radius:50%;background:var(--cyan);box-shadow:0 0 8px var(--cyan)}

  /* ---------- cover ---------- */
  .cover{display:grid;grid-template-columns:1.45fr 1fr;gap:22px;position:relative;overflow:hidden;
    border-radius:20px;padding:30px 34px}
  .cover::before{content:"";position:absolute;inset:0;pointer-events:none;
    background:radial-gradient(520px 280px at 92% 8%, rgba(34,211,238,.14), transparent 70%)}
  .cover-left{display:flex;flex-direction:column;justify-content:center;gap:11px;position:relative;z-index:1}
  .biz-name{font-family:var(--font-display);font-weight:700;font-size:36px;letter-spacing:-.02em;
    line-height:1.06;word-break:break-word}
  .biz-url{font-family:var(--font-mono);font-size:14.5px;color:var(--cyan);word-break:break-all}
  .meta-row{display:flex;gap:26px;flex-wrap:wrap;margin-top:8px}
  .meta-item{display:flex;flex-direction:column;gap:3px}
  .meta-label{font-family:var(--font-mono);font-size:10px;letter-spacing:.11em;text-transform:uppercase;color:var(--low)}
  .meta-val{font-size:14px;font-weight:600;color:var(--hi)}
  .cover-right{display:flex;align-items:center;justify-content:center;gap:22px;position:relative;z-index:1;
    flex-wrap:wrap}
  .ring-wrap{position:relative;display:flex;align-items:center;justify-content:center;flex:0 0 auto}
  .ring-wrap svg{filter:drop-shadow(0 0 20px rgba(59,130,246,.42))}
  .verdict{display:flex;flex-direction:column;gap:9px;max-width:230px}
  .verdict h3{font-family:var(--font-display);font-size:15px;font-weight:600}
  .verdict p{font-size:13px;color:var(--mid);line-height:1.55}

  .grade-pill{display:inline-flex;align-items:center;gap:7px;width:fit-content;padding:4px 11px;
    border-radius:100px;font-family:var(--font-mono);font-size:12px;font-weight:700}

  /* ---------- KPI counters ---------- */
  .kpi-row{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}
  .kpi{background:linear-gradient(160deg,var(--card) 0%,var(--navy) 100%);border:1px solid var(--line);
    border-radius:14px;padding:15px 16px;display:flex;flex-direction:column;gap:5px}
  .kpi .n{font-family:var(--font-display);font-weight:700;font-size:30px;line-height:1;letter-spacing:-.02em}
  .kpi .l{font-family:var(--font-mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--low)}
  .kpi .h{font-size:11.5px;color:var(--mid);line-height:1.4}

  /* ---------- scorecard grid ---------- */
  .scorecard-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:13px}
  .score-card{background:linear-gradient(160deg,var(--card) 0%,var(--navy) 100%);border:1px solid var(--line);
    border-radius:16px;padding:17px 18px 15px;display:flex;flex-direction:column;gap:10px}
  .sc-top{display:flex;align-items:center;justify-content:space-between;gap:8px}
  .sc-icon{width:34px;height:34px;border-radius:9px;display:flex;align-items:center;justify-content:center;
    font-size:16px;background:rgba(59,130,246,.10);border:1px solid rgba(59,130,246,.25);flex:0 0 auto}
  .sc-value{font-family:var(--font-display);font-weight:700;font-size:27px;letter-spacing:-.02em;line-height:1}
  .sc-value small{font-size:12px;font-weight:500;color:var(--low);letter-spacing:0}
  .sc-name{font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--mid)}
  .track{width:100%;height:6px;border-radius:6px;background:rgba(255,255,255,.06);overflow:hidden}
  .track .fill{height:100%;border-radius:6px;display:block}
  .tag{font-family:var(--font-mono);font-size:10.5px;font-weight:500;padding:3px 9px;border-radius:100px;
    width:fit-content;letter-spacing:.03em}

  /* ---------- charts ---------- */
  .charts-row{display:grid;grid-template-columns:1.25fr 1fr 1fr;gap:13px}
  .charts-row.two{grid-template-columns:1fr 1.25fr}
  .chart-card{background:linear-gradient(160deg,var(--card) 0%,var(--navy) 100%);border:1px solid var(--line);
    border-radius:16px;padding:19px 21px;display:flex;flex-direction:column;gap:13px}
  .chart-title{font-family:var(--font-display);font-size:14.5px;font-weight:700}
  .chart-title span{display:block;margin-top:3px;font-family:var(--font-mono);font-size:11px;
    font-weight:400;color:var(--low);letter-spacing:.02em}
  .bar-chart{display:flex;flex-direction:column;gap:9px}
  .bar-row{display:grid;grid-template-columns:118px 1fr 38px;align-items:center;gap:11px}
  .bar-row .lbl{font-size:11.5px;font-weight:600;color:var(--mid)}
  .bar-row .val{font-family:var(--font-mono);font-size:12px;color:var(--hi);text-align:right}
  .bar-row .val.na{color:var(--low);font-size:10.5px}
  .donut-wrap{display:flex;align-items:center;gap:16px;flex:1;flex-wrap:wrap}
  .donut-legend{display:flex;flex-direction:column;gap:8px;min-width:130px;flex:1}
  .legend-item{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--mid)}
  .legend-dot{width:9px;height:9px;border-radius:3px;flex:0 0 auto}
  .legend-item b{margin-left:auto;padding-left:12px;color:var(--hi);font-family:var(--font-mono);font-weight:500}

  /* ---------- priorities ---------- */
  .prio-list{display:flex;flex-direction:column;gap:11px}
  .prio-item{display:grid;grid-template-columns:auto 1fr;gap:14px;align-items:start;
    background:var(--raise);border:1px solid var(--line);border-radius:13px;padding:14px 16px}
  .prio-num{flex-shrink:0;width:28px;height:28px;border-radius:9px;
    background:linear-gradient(135deg,var(--blue),var(--cyan));display:flex;align-items:center;
    justify-content:center;font-family:var(--font-mono);font-weight:700;font-size:12.5px;color:#04101f;
    box-shadow:0 0 14px rgba(59,130,246,.35)}
  .prio-head{display:flex;flex-wrap:wrap;gap:7px;align-items:center;margin-bottom:6px}
  .prio-title{font-weight:700;font-size:14px;color:var(--hi)}
  .prio-detail{font-size:12.5px;color:var(--mid);line-height:1.55}
  .prio-action{font-size:12.5px;color:var(--hi);line-height:1.55;margin-top:7px;
    background:rgba(34,211,238,.06);border-left:2px solid var(--cyan);border-radius:0 8px 8px 0;padding:8px 12px}
  .prio-action b{color:var(--cyan)}

  /* ---------- badges ---------- */
  .badge{font-family:var(--font-mono);font-size:10px;font-weight:700;letter-spacing:.07em;
    padding:3px 8px;border-radius:6px;white-space:nowrap;text-transform:uppercase}
  .b-critical{background:rgba(251,91,111,.14);color:var(--red);border:1px solid rgba(251,91,111,.42)}
  .b-high{background:rgba(251,146,60,.13);color:var(--orange);border:1px solid rgba(251,146,60,.42)}
  .b-medium{background:rgba(251,191,36,.13);color:var(--amber);border:1px solid rgba(251,191,36,.40)}
  .b-low{background:rgba(59,130,246,.13);color:#7fb0ff;border:1px solid rgba(59,130,246,.40)}
  .b-pass{background:rgba(52,211,153,.12);color:var(--green);border:1px solid rgba(52,211,153,.38)}
  .b-neutral{background:rgba(148,178,255,.07);color:var(--slate);border:1px solid var(--line)}
  .b-cat{background:rgba(139,92,246,.12);color:#b79dff;border:1px solid rgba(139,92,246,.34);
    text-transform:none;letter-spacing:.02em}
  .b-code{background:rgba(255,255,255,.03);color:var(--low);border:1px solid var(--line);
    text-transform:none;letter-spacing:0;font-weight:500;white-space:normal;word-break:break-all}

  /* ---------- issue cards ---------- */
  .cat-header{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
  .sec-num{width:38px;height:38px;border-radius:11px;display:flex;align-items:center;justify-content:center;
    font-family:var(--font-mono);font-weight:700;font-size:14px;color:#04101f;flex:0 0 auto;
    background:linear-gradient(135deg,var(--cyan),var(--blue));box-shadow:0 0 16px rgba(59,130,246,.3)}
  .cat-header h2{font-family:var(--font-display);font-size:21px;font-weight:700;letter-spacing:-.01em}
  .cat-score{margin-left:auto;display:flex;align-items:center;gap:10px}
  .cat-score .n{font-family:var(--font-display);font-weight:700;font-size:26px;letter-spacing:-.02em}
  .cat-why{font-size:13px;color:var(--mid);line-height:1.6;margin-top:2px}

  .flabel{font-family:var(--font-mono);font-size:10px;font-weight:700;letter-spacing:.13em;
    text-transform:uppercase;color:var(--low);margin-bottom:5px}

  .finding{background:var(--raise);border:1px solid var(--line);border-left-width:3px;border-radius:13px;
    padding:17px 19px;display:flex;flex-direction:column;gap:12px}
  .finding.high{border-left-color:var(--red)}
  .finding.medium{border-left-color:var(--orange)}
  .finding.low{border-left-color:var(--amber)}
  .finding-head{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
  .finding-title{font-family:var(--font-display);font-size:15.5px;font-weight:600;
    letter-spacing:-.01em;width:100%;line-height:1.35}
  .field p{font-size:13.5px;color:var(--mid);line-height:1.62}
  .field.fix{background:rgba(34,211,238,.05);border:1px solid rgba(34,211,238,.18);
    border-radius:10px;padding:12px 14px}
  .field.fix p{color:#cfeaf6}
  .field.fix .flabel{color:var(--cyan)}
  .ev-list{display:flex;flex-direction:column;gap:5px;background:rgba(0,0,0,.24);
    border:1px solid var(--line);border-radius:10px;padding:11px 13px}
  .ev-row{display:grid;grid-template-columns:minmax(110px,auto) 1fr;gap:12px;
    font-family:var(--font-mono);font-size:11.5px;line-height:1.5}
  .ev-row .k{color:var(--low);text-transform:uppercase;letter-spacing:.06em;font-size:10.5px;padding-top:1px}
  .ev-row .v{color:#c9d6f5;word-break:break-word}
  .findings-list{display:flex;flex-direction:column;gap:12px}

  /* ---------- check rows ---------- */
  .check-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}
  .check-grid.one{grid-template-columns:1fr}
  .cat-index{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:14px}
  .check-row{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:10px;
    background:var(--raise);border:1px solid var(--line);font-size:12.5px}
  .check-row .icon{width:18px;height:18px;border-radius:50%;display:flex;align-items:center;
    justify-content:center;font-size:10px;font-weight:700;color:#04101f;flex:0 0 auto}
  .check-row .label{color:var(--mid);flex:1}
  .check-row .why{color:var(--low);font-size:11.5px}

  /* ---------- tables / signals ---------- */
  .sig-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:10px}
  .sig{background:var(--raise);border:1px solid var(--line);border-radius:12px;padding:12px 14px;
    display:flex;flex-direction:column;gap:4px}
  .sig .k{font-family:var(--font-mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--low)}
  .sig .v{font-size:13.5px;font-weight:600;color:var(--hi);word-break:break-word;line-height:1.45}
  .sig .v.na{color:var(--slate);font-weight:500}
  .sig .why{font-size:11.5px;color:var(--low);line-height:1.45}

  /* Grid/flex children default to min-width:auto, which lets a long token push
     the whole document wider than the viewport. Nothing here should ever make
     the page itself scroll sideways - wide content scrolls inside its own box. */
  .doc > *, .page > *, .lower-row > *, .charts-row > *, .scorecard-grid > *,
  .kpi-row > *, .check-grid > *, .cat-index > *, .sig-grid > *, .bar-row > *,
  .donut-wrap > *, .prio-item > *, .finding > *{min-width:0}
  .table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
  table{width:100%;min-width:420px;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:9px 11px;border-bottom:1px solid var(--line);vertical-align:top}
  th{font-family:var(--font-mono);color:var(--low);font-weight:500;font-size:10.5px;
    text-transform:uppercase;letter-spacing:.1em}
  td{color:var(--mid)}
  td code,code{font-family:var(--font-mono);font-size:12px;color:#c9d6f5;background:rgba(0,0,0,.28);
    padding:2px 6px;border-radius:5px;word-break:break-all}

  .note{font-size:12.5px;color:var(--low);line-height:1.65}
  .banner{border:1px dashed var(--line-bright);background:rgba(148,178,255,.03);border-radius:13px;
    padding:18px 20px;font-size:13px;color:var(--mid);line-height:1.65}
  .banner b{color:var(--hi)}
  .banner.na{text-align:center}
  .disclosure{background:rgba(148,178,255,.03);border:1px dashed var(--line-bright);border-radius:11px;
    padding:12px 14px;font-size:12.5px;color:var(--low);line-height:1.6}
  .disclosure b{color:var(--mid)}
  .empty{font-size:13px;color:var(--low)}

  .stack{display:flex;flex-direction:column;gap:14px}
  .stack .spacer{flex:1;min-height:0}
  .stackbar{display:flex;width:100%;height:13px;border-radius:7px;overflow:hidden;
    background:rgba(255,255,255,.06)}
  .stackbar span{height:100%;display:block}
  .stackbar-legend{display:flex;flex-wrap:wrap;gap:16px;margin-top:9px;font-size:12px;color:var(--mid)}
  .stackbar-legend i{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:6px}
  .stackbar-legend b{color:var(--hi);font-family:var(--font-mono);font-weight:500}
  .lower-row{display:grid;grid-template-columns:1.4fr 1fr;gap:13px;align-items:stretch}

  footer.doc-footer{text-align:center;color:var(--low);font-size:11.5px;line-height:1.85;
    padding:22px 0 4px;border-top:1px solid var(--line);font-family:var(--font-mono);letter-spacing:.02em}

  /* ---------- responsive ---------- */
  @media (max-width:1100px){
    .cover{grid-template-columns:1fr}
    .cover-right{justify-content:flex-start}
    .scorecard-grid{grid-template-columns:repeat(2,1fr)}
    .charts-row{grid-template-columns:1fr}
    .lower-row{grid-template-columns:1fr}
    .charts-row.two{grid-template-columns:1fr}
    .kpi-row{grid-template-columns:repeat(3,1fr)}
    .check-grid{grid-template-columns:1fr}
    .cat-index{grid-template-columns:repeat(2,1fr)}
  }
  @media (max-width:640px){
    body{padding:16px 12px 40px}
    .card{padding:19px 17px}
    .cover{padding:22px 20px}
    .biz-name{font-size:27px}
    .scorecard-grid{grid-template-columns:1fr}
    .kpi-row{grid-template-columns:repeat(2,1fr)}
    .cat-index{grid-template-columns:1fr}
    .bar-row{grid-template-columns:96px 1fr 34px}
    .ev-row{grid-template-columns:1fr;gap:1px}
  }

  /* ---------- print: flip to an ink-friendly light document ---------- */
  @media print{
    :root{
      --void:#fff; --navy:#fff; --card:#fff; --card-2:#f7f8fc; --raise:#fbfcff;
      --line:#dfe3ee; --line-bright:#c8cfe0;
      --hi:#0f1424; --mid:#3a4257; --low:#69718a; --slate:#69718a;
      --green:#1c7a52; --amber:#8a6a05; --orange:#a3560a; --red:#b32a3d;
      --blue:#2b5fd0; --cyan:#0e7f97;
    }
    body{background:#fff !important;padding:0;font-size:11.5pt}
    .doc{max-width:none;gap:10px}
    .card,.kpi,.score-card,.chart-card{background:#fff !important;border:1px solid #dfe3ee !important;
      box-shadow:none !important;break-inside:avoid}
    .cover::before{display:none}
    .ring-wrap svg{filter:none}
    .prio-num,.sec-num{box-shadow:none;color:#fff;background:#2b5fd0}
    .finding,.prio-item,.check-row,.sig{background:#fbfcff !important;break-inside:avoid}
    .ev-list{background:#f4f6fb !important}
    .field.fix{background:#f0f8fb !important}
    code,td code{background:#f1f3f9;color:#25304a}
    a{color:#2b5fd0}
    .table-wrap{overflow:visible}
    table{min-width:0}
  }
  @page{
    margin:14mm 12mm 16mm;
    @bottom-center{ content:"Page " counter(page) " of " counter(pages); font-size:8.5pt; color:#8a90a3; }
    @top-right{ content:"{{ business.name|e }} — Website Audit"; font-size:8pt; color:#a3a8b8; }
  }
</style>
</head>
<body>
<div class="doc">

  <!-- ============================ PAGE 1 — EXECUTIVE SUMMARY ============================ -->
  <div class="page">

    <header class="card cover">
      <div class="cover-left">
        <div class="eyebrow"><span class="dot"></span> Website Intelligence Report</div>
        <div class="biz-name">{{ business.name }}</div>
        {% if audit.website %}
        <a class="biz-url" href="{{ audit.website }}" rel="noopener nofollow">{{ audit.website }}</a>
        {% else %}
        <div class="biz-url" style="color:var(--slate)">No website was available to audit</div>
        {% endif %}
        <div class="meta-row">
          {% for m in cover_meta %}
          <div class="meta-item">
            <div class="meta-label">{{ m.label }}</div>
            <div class="meta-val">{{ m.value }}</div>
          </div>
          {% endfor %}
        </div>
      </div>
      <div class="cover-right">
        <div class="ring-wrap">{{ ring_overall|safe }}</div>
        <div class="verdict">
          <h3>Overall Website Health</h3>
          <p>{{ executive_summary.headline or 'This website could not be fully audited.' }}</p>
          {% if grade %}
          <span class="grade-pill" style="background:{{ overall_band.soft }};border:1px solid {{ overall_band.edge }};color:{{ overall_band.fg }}">
            GRADE {{ grade }} · {{ overall_band.label|upper }}
          </span>
          {% endif %}
        </div>
      </div>
    </header>

    {% if scorecard %}
    <div class="kpi-row">
      <div class="kpi">
        <div class="n" style="color:var(--red)">{{ scorecard.severity_counts.high }}</div>
        <div class="l">Critical issues</div>
        <div class="h">Fix first — actively costing visibility or trust</div>
      </div>
      <div class="kpi">
        <div class="n" style="color:var(--orange)">{{ scorecard.severity_counts.medium }}</div>
        <div class="l">High priority</div>
        <div class="h">Material impact, should be scheduled now</div>
      </div>
      <div class="kpi">
        <div class="n" style="color:var(--amber)">{{ scorecard.severity_counts.low }}</div>
        <div class="l">Warnings</div>
        <div class="h">Smaller gaps worth tidying up</div>
      </div>
      <div class="kpi">
        <div class="n" style="color:var(--green)">{{ checks.passed_count }}</div>
        <div class="l">Checks passed</div>
        <div class="h">Of {{ checks.total_checked }} checks that could be evaluated</div>
      </div>
      <div class="kpi">
        <div class="n" style="color:var(--slate)">{{ checks.not_verified_count }}</div>
        <div class="l">Not verified</div>
        <div class="h">Needs a paid data source or a rendered browser</div>
      </div>
      <div class="kpi">
        <div class="n" style="color:var(--slate)">{{ checks.not_applicable_count }}</div>
        <div class="l">Not applicable</div>
        <div class="h">Does not apply to this type of website</div>
      </div>
    </div>

    <div class="section-head">
      <div class="section-title"><span class="bar"></span>Visual Scorecard</div>
      <div class="section-sub">{{ scorecard.categories|length }} categories · weighted model · higher is better</div>
    </div>
    <div class="scorecard-grid">
      {% for c in scorecard.categories %}
      <div class="score-card">
        <div class="sc-top">
          <div class="sc-icon">{{ c.icon }}</div>
          {% if c.applicable and c.score is not none %}
          <div class="sc-value" style="color:{{ c.band.fg }}">{{ c.score }}<small>/100</small></div>
          {% else %}
          <div class="sc-value" style="color:var(--slate);font-size:19px">N/A</div>
          {% endif %}
        </div>
        <div class="sc-name">{{ c.label }}</div>
        <div class="track">
          {% if c.applicable and c.score is not none %}
          <span class="fill" style="width:{{ c.score }}%;background:linear-gradient(90deg,{{ c.band.g1 }},{{ c.band.g2 }})"></span>
          {% else %}
          <span class="fill" style="width:100%;background:rgba(148,178,255,.10)"></span>
          {% endif %}
        </div>
        <span class="tag" style="background:{{ c.band.soft }};color:{{ c.band.fg }}">{{ c.band.label }}</span>
      </div>
      {% endfor %}
    </div>

    <div class="section-head">
      <div class="section-title"><span class="bar"></span>Executive summary</div>
      <div class="section-sub">What this means for the business</div>
    </div>
    <div class="lower-row">
      <section class="card stack">
        <div>
          <div class="flabel">Business impact</div>
          <p style="font-size:14px;color:var(--mid);line-height:1.65">{{ executive_summary.business_impact }}</p>
        </div>
        <div class="check-grid">
          <div>
            <div class="flabel">✓ What is working</div>
            {% if executive_summary.whats_working %}
            <ul style="margin:0;padding-left:17px;font-size:13px;color:var(--mid);line-height:1.8">
              {% for w in executive_summary.whats_working %}<li>{{ w }}</li>{% endfor %}
            </ul>
            {% else %}
            <p class="empty">No category currently scores in the “Good” range (85+).</p>
            {% endif %}
          </div>
          <div>
            <div class="flabel">↑ Biggest opportunities</div>
            {% if executive_summary.biggest_opportunities %}
            <ul style="margin:0;padding-left:17px;font-size:13px;color:var(--mid);line-height:1.8">
              {% for o in executive_summary.biggest_opportunities %}<li>{{ o }}</li>{% endfor %}
            </ul>
            {% else %}
            <p class="empty">No applicable category scores below 70.</p>
            {% endif %}
          </div>
        </div>
        <div class="spacer"></div>
        <div>
          <div class="flabel">Checks evaluated — passed vs warning vs failed</div>
          <div class="stackbar">
            {% if check_bar.total %}
            <span style="width:{{ check_bar.pass_pct }}%;background:linear-gradient(90deg,#34d399,#22d3ee)"></span>
            <span style="width:{{ check_bar.warn_pct }}%;background:linear-gradient(90deg,#f59e0b,#fbbf24)"></span>
            <span style="width:{{ check_bar.fail_pct }}%;background:linear-gradient(90deg,#fb5b6f,#fb923c)"></span>
            {% endif %}
          </div>
          <div class="stackbar-legend">
            <span><i style="background:#34d399"></i>Passed <b>{{ checks.passed_count }}</b></span>
            <span><i style="background:#fbbf24"></i>Warning <b>{{ checks.warning_count }}</b></span>
            <span><i style="background:#fb5b6f"></i>Failed <b>{{ checks.failed_count }}</b></span>
            <span><i style="background:#55607d"></i>Not verified / not applicable
              <b>{{ checks.not_verified_count + checks.not_applicable_count }}</b></span>
          </div>
        </div>
      </section>

      <section class="card">
        <div class="flabel" style="margin-bottom:11px">→ Recommended next steps</div>
        {% if executive_summary.next_steps %}
        <div class="prio-list">
          {% for n in executive_summary.next_steps %}
          <div class="prio-item" style="padding:11px 13px">
            <div class="prio-num">{{ loop.index }}</div>
            <div class="prio-detail" style="color:var(--hi);padding-top:3px">{{ n }}</div>
          </div>
          {% endfor %}
        </div>
        {% else %}
        <p class="empty">No outstanding actions were produced by this audit.</p>
        {% endif %}
      </section>
    </div>

    <div class="section-head">
      <div class="section-title"><span class="bar"></span>Top 5 priorities</div>
      <div class="section-sub">Ranked by measured severity and impact</div>
    </div>
    <section class="card">
      {% if priorities %}
      <div class="prio-list">
        {% for p in priorities %}
        <div class="prio-item">
          <div class="prio-num">{{ p.rank }}</div>
          <div>
            <div class="prio-head">
              <span class="badge b-{{ p.badge_class }}">{{ p.severity_badge }}</span>
              <span class="badge b-neutral">{{ p.priority }}</span>
              <span class="badge b-cat">{{ p.category_label }}</span>
            </div>
            <div class="prio-title">{{ p.title }}</div>
            <div class="prio-detail">{{ p.detail }}</div>
            {% if p.recommendation %}
            <div class="prio-action"><b>Recommended action:</b> {{ p.recommendation }}</div>
            {% endif %}
          </div>
        </div>
        {% endfor %}
      </div>
      {% else %}
      <p class="empty">No priority issues were detected within the checks this audit performs.
        No issues have been invented to fill this section.</p>
      {% endif %}
    </section>
  </div>

  <!-- ============================ PAGE 2 — VISUAL ANALYTICS ============================ -->
  <div class="page">
    <div class="section-head">
      <div class="section-title"><span class="bar"></span>Visual analytics</div>
      <div class="section-sub">{{ checks.total_catalogued }} checks evaluated · {{ findings.all|length }} findings</div>
    </div>
    <div class="charts-row">
      <div class="chart-card">
        <div class="chart-title">Category scores<span>Weighted 0–100 · higher is better</span></div>
        <div class="bar-chart">
          {% for c in scorecard.categories %}
          <div class="bar-row">
            <div class="lbl">{{ c.label }}</div>
            <div class="track">
              {% if c.applicable and c.score is not none %}
              <span class="fill" style="width:{{ c.score }}%;background:linear-gradient(90deg,{{ c.band.g1 }},{{ c.band.g2 }})"></span>
              {% else %}
              <span class="fill" style="width:100%;background:rgba(148,178,255,.09)"></span>
              {% endif %}
            </div>
            {% if c.applicable and c.score is not none %}
            <div class="val">{{ c.score }}</div>
            {% else %}
            <div class="val na">N/A</div>
            {% endif %}
          </div>
          {% endfor %}
        </div>
      </div>

      <div class="chart-card">
        <div class="chart-title">Issues by severity<span>{{ total_issues }} finding(s) with a measured impact</span></div>
        <div class="donut-wrap">
          {{ donut_severity|safe }}
          <div class="donut-legend">
            <div class="legend-item"><span class="legend-dot" style="background:#fb5b6f"></span>Critical<b>{{ scorecard.severity_counts.high }}</b></div>
            <div class="legend-item"><span class="legend-dot" style="background:#fb923c"></span>High<b>{{ scorecard.severity_counts.medium }}</b></div>
            <div class="legend-item"><span class="legend-dot" style="background:#fbbf24"></span>Medium<b>{{ scorecard.severity_counts.low }}</b></div>
          </div>
        </div>
      </div>

      <div class="chart-card">
        <div class="chart-title">Checks by status<span>Passed vs warning vs failed</span></div>
        <div class="donut-wrap">
          {{ donut_status|safe }}
          <div class="donut-legend">
            <div class="legend-item"><span class="legend-dot" style="background:#34d399"></span>Passed<b>{{ checks.passed_count }}</b></div>
            <div class="legend-item"><span class="legend-dot" style="background:#fbbf24"></span>Warning<b>{{ checks.warning_count }}</b></div>
            <div class="legend-item"><span class="legend-dot" style="background:#fb5b6f"></span>Failed<b>{{ checks.failed_count }}</b></div>
            <div class="legend-item"><span class="legend-dot" style="background:#55607d"></span>N/V or N/A<b>{{ checks.not_verified_count + checks.not_applicable_count }}</b></div>
          </div>
        </div>
      </div>
    </div>

    <div class="charts-row two">
      <div class="chart-card">
        <div class="chart-title">Priority distribution<span>P1 fix now · P2 next · P3 backlog</span></div>
        <div class="donut-wrap">
          {{ donut_priority|safe }}
          <div class="donut-legend">
            <div class="legend-item"><span class="legend-dot" style="background:#fb5b6f"></span>P1 — fix now<b>{{ priority_counts.P1 }}</b></div>
            <div class="legend-item"><span class="legend-dot" style="background:#fb923c"></span>P2 — next<b>{{ priority_counts.P2 }}</b></div>
            <div class="legend-item"><span class="legend-dot" style="background:#3b82f6"></span>P3 — backlog<b>{{ priority_counts.P3 }}</b></div>
          </div>
        </div>
      </div>

      <div class="chart-card">
        <div class="chart-title">Findings per category<span>Where the measured problems actually are</span></div>
        <div class="bar-chart">
          {% for row in findings_per_category %}
          <div class="bar-row">
            <div class="lbl">{{ row.label }}</div>
            <div class="track">
              <span class="fill" style="width:{{ row.pct }}%;background:linear-gradient(90deg,{{ row.g1 }},{{ row.g2 }})"></span>
            </div>
            <div class="val">{{ row.count }}</div>
          </div>
          {% endfor %}
        </div>
      </div>
    </div>

    <div class="section-head">
      <div class="section-title"><span class="bar"></span>Verified signals</div>
      <div class="section-sub">Measured directly from this website — nothing estimated</div>
    </div>
    <section class="card">
      <div class="sig-grid">
        {% for s in signals %}
        <div class="sig">
          <div class="k">{{ s.label }}</div>
          <div class="v {{ 'na' if s.na else '' }}">{{ s.value }}</div>
          {% if s.why %}<div class="why">{{ s.why }}</div>{% endif %}
        </div>
        {% endfor %}
      </div>
      <div class="disclosure" style="margin-top:14px">
        <b>Not Verified — external verification unavailable.</b>
        Backlinks, referring domains, domain-authority-style scores, organic traffic, keyword rankings
        and search volume all require a paid third-party index. None is configured for this audit, so
        none of those figures appear anywhere in this report — they are not estimated, modelled or guessed.
      </div>
    </section>
  </div>
  {% endif %}

  <!-- ==================== ISSUES &amp; RECOMMENDATIONS (per category) ==================== -->
  {% if category_sections %}
  <div class="page">
    <div class="section-head">
      <div class="section-title"><span class="bar"></span>Issues &amp; Recommendations</div>
      <div class="section-sub">Every detected issue · what · why · how · evidence · priority</div>
    </div>
    <section class="card">
      <div class="note" style="color:var(--mid)">
        Each of the {{ category_sections|length }} sections that follow covers one audit category. Every
        finding lists <b style="color:var(--hi)">What we found</b>, <b style="color:var(--hi)">Why it matters</b>,
        <b style="color:var(--hi)">How to fix</b> it, the <b style="color:var(--hi)">Evidence</b> that
        triggered it, and a <b style="color:var(--hi)">Priority</b>. Checks that passed are listed too, so a
        clean category is visibly clean rather than simply absent. Anything the engine could not measure is
        labelled <b style="color:var(--hi)">Not verified</b> with the reason, and anything that does not apply
        to this website is labelled <b style="color:var(--hi)">Not Applicable</b> with the reason.
      </div>
      <div class="cat-index">
        {% for cat in category_sections %}
        <div class="check-row">
          <span class="badge b-neutral">{{ cat.number }}</span>
          <span class="label">{{ cat.label }}</span>
          {% if cat.applicable %}
          <span class="badge b-{{ cat.count_class }}">{{ cat.findings|length }}</span>
          {% else %}
          <span class="badge b-neutral">N/A</span>
          {% endif %}
        </div>
        {% endfor %}
      </div>
    </section>
  </div>

  {% for cat in category_sections %}
  <div class="page" id="cat-{{ cat.key }}">
    <section class="card stack">
      <div class="cat-header">
        <div class="sec-num">{{ cat.number }}</div>
        <h2>{{ cat.label }}</h2>
        <div class="cat-score">
          {% if cat.applicable and cat.score is not none %}
          <span class="n" style="color:{{ cat.band.fg }}">{{ cat.score }}<small style="font-size:13px;color:var(--low)">/100</small></span>
          <span class="tag" style="background:{{ cat.band.soft }};color:{{ cat.band.fg }}">{{ cat.band.label }}</span>
          {% else %}
          <span class="tag" style="background:rgba(148,178,255,.07);color:var(--slate)">Not Applicable</span>
          {% endif %}
        </div>
      </div>
      <p class="cat-why">{{ cat.why_it_matters }}</p>

      {% if not cat.applicable %}
      <div class="banner na">
        <b>Not applicable to this website.</b><br>{{ cat.not_applicable_reason }}
      </div>
      {% else %}

      {% if cat.findings %}
      <div>
        <div class="flabel">What needs improvement — {{ cat.findings|length }} finding{{ 's' if cat.findings|length != 1 else '' }}</div>
        <div class="findings-list">
          {% for p in cat.findings %}
          <article class="finding {{ p.severity }}">
            <div class="finding-head">
              <span class="badge b-{{ p.badge_class }}">{{ p.severity_badge }}</span>
              <span class="badge b-neutral">{{ p.priority }}</span>
              <span class="badge b-code">{{ p.code }}</span>
              {% if p.deduction %}<span class="badge b-neutral">−{{ p.deduction }} pts</span>{% endif %}
              <div class="finding-title">{{ p.title }}</div>
            </div>
            <div class="field">
              <div class="flabel">What we found</div>
              <p>{{ p.detail }}</p>
            </div>
            {% if p.why_it_matters %}
            <div class="field">
              <div class="flabel">Why it matters</div>
              <p>{{ p.why_it_matters }}</p>
            </div>
            {% endif %}
            {% if p.recommendation %}
            <div class="field fix">
              <div class="flabel">How to fix</div>
              <p>{{ p.recommendation }}</p>
            </div>
            {% endif %}
            {% if p.evidence_rows %}
            <div class="field">
              <div class="flabel">Evidence — measured on this site</div>
              <div class="ev-list">
                {% for e in p.evidence_rows %}
                <div class="ev-row"><span class="k">{{ e.k }}</span><span class="v">{{ e.v }}</span></div>
                {% endfor %}
              </div>
            </div>
            {% endif %}
          </article>
          {% endfor %}
        </div>
      </div>
      {% else %}
      <div class="banner">
        <b>No evidence-backed issues were detected in this category.</b><br>
        Nothing has been invented to fill this section.
      </div>
      {% endif %}

      {% if cat.passed_checks %}
      <div>
        <div class="flabel">Passed — {{ cat.passed_checks|length }} check{{ 's' if cat.passed_checks|length != 1 else '' }}</div>
        <div class="check-grid">
          {% for chk in cat.passed_checks %}
          <div class="check-row">
            <span class="icon" style="background:var(--green)">✓</span>
            <span class="label">{{ chk.label }}</span>
            <span class="badge b-pass">PASS</span>
          </div>
          {% endfor %}
        </div>
      </div>
      {% endif %}

      {% if cat.not_verified_checks %}
      <div>
        <div class="flabel">Not verified — could not be measured by this engine</div>
        <div class="check-grid one">
          {% for chk in cat.not_verified_checks %}
          <div class="check-row">
            <span class="icon" style="background:var(--slate)">?</span>
            <span class="label">{{ chk.label }} <span class="why">— {{ chk.detail }}</span></span>
            <span class="badge b-neutral">NOT VERIFIED</span>
          </div>
          {% endfor %}
        </div>
      </div>
      {% endif %}

      {% if cat.signals %}
      <div>
        <div class="flabel">Technical context for this category</div>
        <div class="sig-grid">
          {% for s in cat.signals %}
          <div class="sig">
            <div class="k">{{ s.label }}</div>
            <div class="v {{ 'na' if s.na else '' }}">{{ s.value }}</div>
            {% if s.why %}<div class="why">{{ s.why }}</div>{% endif %}
          </div>
          {% endfor %}
        </div>
      </div>
      {% endif %}

      {% if cat.disclosure %}
      <div class="disclosure"><b>Not verified:</b> {{ cat.disclosure }}</div>
      {% endif %}
      {% endif %}
    </section>
  </div>
  {% endfor %}
  {% endif %}

  <!-- ==================== FALLBACK (no scorecard available) ==================== -->
  {% if not scorecard %}
  <div class="page">
    <section class="card">
      <div class="flabel">Audit status</div>
      <p style="font-size:14px;color:var(--mid);line-height:1.65;margin-top:6px">
        {{ audit.audit_error or 'This website could not be fully audited. What was checked is listed below.' }}
      </p>
    </section>

    <section class="card">
      <div class="section-title" style="font-size:17px;margin-bottom:14px">
        <span class="bar"></span>Detected problems{% if problems %} — {{ problems|length }}{% endif %}
      </div>
      {% if problems %}
      <div class="findings-list">
        {% for p in problems %}
        <article class="finding {{ p.severity }}">
          <div class="finding-head">
            <span class="badge b-{{ p.badge_class }}">{{ p.severity_badge }}</span>
            <div class="finding-title">{{ p.title }}</div>
          </div>
          <div class="field"><div class="flabel">What we found</div><p>{{ p.detail }}</p></div>
          {% if p.recommendation %}
          <div class="field fix"><div class="flabel">How to fix</div><p>{{ p.recommendation }}</p></div>
          {% endif %}
          {% if p.evidence_rows %}
          <div class="field">
            <div class="flabel">Evidence</div>
            <div class="ev-list">
              {% for e in p.evidence_rows %}
              <div class="ev-row"><span class="k">{{ e.k }}</span><span class="v">{{ e.v }}</span></div>
              {% endfor %}
            </div>
          </div>
          {% endif %}
        </article>
        {% endfor %}
      </div>
      {% else %}
      <p class="empty">
        No evidence-backed problems were detected within the checks this audit performs.
        No issues have been invented to fill this section.
      </p>
      {% endif %}
    </section>
  </div>
  {% endif %}

  <!-- ============================== APPENDIX ============================== -->
  <div class="page">
    <div class="section-head">
      <div class="section-title"><span class="bar"></span>Appendix</div>
      <div class="section-sub">Method, raw measurements and scope</div>
    </div>

    <section class="card">
      <div class="flabel" style="margin-bottom:12px">What was measured</div>
      <div class="table-wrap">
        <table>
          <tbody>
            {% for row in measured %}
            <tr><th style="width:40%">{{ row.label }}</th><td>{{ row.value }}</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      <p class="note" style="margin-top:14px">{{ method_note }}</p>
    </section>

    {% if contacts %}
    <section class="card">
      <div class="flabel" style="margin-bottom:12px">Contact options found on the site</div>
      <div class="sig-grid">
        {% for c in contacts %}
        <div class="sig">
          <div class="k">{{ c.label }}</div>
          <div class="v">{{ c.value }}{% if c.status %} <span class="badge b-neutral">{{ c.status }}</span>{% endif %}</div>
        </div>
        {% endfor %}
      </div>
      <p class="note" style="margin-top:12px">
        Listed here only if found publicly on the business's own website or supplied in the source data.
        Nothing was guessed or constructed.
      </p>
    </section>
    {% endif %}

    {% if pages %}
    <section class="card">
      <div class="flabel" style="margin-bottom:12px">Pages reviewed — {{ pages|length }}</div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Type</th><th>URL</th><th style="width:78px">Status</th></tr></thead>
          <tbody>
            {% for pg in pages %}
            <tr><td>{{ pg.type }}</td><td><code>{{ pg.url }}</code></td><td>{{ pg.status }}</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </section>
    {% endif %}

    <footer class="doc-footer">
      Audit generated {{ generated_at }}{% if generator %} by {{ generator }}{% endif %}.<br>
      Findings are limited to what could be observed from publicly accessible pages at that time.
      No performance, ranking, backlink, traffic, review-count or revenue claims are made beyond the
      measurements shown in this report. Checks that could not be measured are labelled
      “Not verified”; categories that do not apply to this site are labelled “Not Applicable” —
      neither is ever scored as if it had passed or failed.
    </footer>
  </div>

</div>
</body>
</html>
"""

# ============================================================================
# Inline-SVG chart helpers - no external JS/CSS libraries, so the report stays
# a single self-contained file suitable for printing to PDF.
# ============================================================================


def _svg_ring(
    score: Optional[int],
    size: int = 188,
    stroke: int = 15,
    g1: str = "#22d3ee",
    g2: str = "#3b82f6",
    uid: str = "ring",
) -> str:
    """Big gradient progress ring with the score set in the middle."""
    r = size / 2 - stroke - 4
    cx = cy = size / 2
    circ = 2 * math.pi * r
    pct = 0 if score is None else max(0, min(100, score))
    dash = circ * pct / 100
    label = "—" if score is None else str(score)
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img" '
        f'aria-label="Overall score {label} out of 100">'
        f'<defs><linearGradient id="{uid}" x1="0%" y1="0%" x2="100%" y2="100%">'
        f'<stop offset="0%" stop-color="{g1}"/><stop offset="100%" stop-color="{g2}"/>'
        f'</linearGradient></defs>'
        f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="none" stroke="rgba(148,178,255,.10)" stroke-width="{stroke}"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="none" stroke="url(#{uid})" stroke-width="{stroke}" '
        f'stroke-dasharray="{dash:.2f} {circ:.2f}" stroke-linecap="round" transform="rotate(-90 {cx} {cy})"/>'
        f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" fill="{g2}" '
        f'font-family="Space Grotesk,Segoe UI,sans-serif" font-weight="700" font-size="{round(size * 0.28)}">{label}</text>'
        f'<text x="{cx}" y="{cy + round(size * 0.19)}" text-anchor="middle" fill="#6b7593" '
        f'font-family="JetBrains Mono,monospace" font-size="{round(size * 0.068)}">/ 100</text>'
        f'</svg>'
    )


def _svg_donut(
    segments: List[Dict[str, Any]],
    size: int = 148,
    stroke: int = 19,
    center_label: str = "",
    center_sub: str = "",
) -> str:
    """Segmented donut. Renders an explicit empty state rather than a fake slice."""
    total = sum(max(0, int(s.get("value", 0) or 0)) for s in segments)
    r = size / 2 - stroke / 2 - 3
    cx = cy = size / 2
    circ = 2 * math.pi * r
    head = (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img" '
        f'aria-label="{center_sub or "distribution"} chart">'
        f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="none" stroke="rgba(148,178,255,.09)" stroke-width="{stroke}"/>'
    )
    body = ""
    if total > 0:
        offset = 0.0
        for s in segments:
            v = max(0, int(s.get("value", 0) or 0))
            if v == 0:
                continue
            dash = circ * (v / total)
            body += (
                f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="none" stroke="{s["color"]}" '
                f'stroke-width="{stroke}" stroke-dasharray="{dash:.2f} {circ:.2f}" '
                f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})"/>'
            )
            offset += dash
    label = center_label if center_label != "" else str(total)
    text = (
        f'<text x="{cx}" y="{cy - 1}" text-anchor="middle" fill="#f4f7ff" '
        f'font-family="Space Grotesk,Segoe UI,sans-serif" font-weight="700" font-size="{round(size * 0.185)}">{label}</text>'
    )
    if center_sub:
        text += (
            f'<text x="{cx}" y="{cy + round(size * 0.13)}" text-anchor="middle" fill="#6b7593" '
            f'font-family="JetBrains Mono,monospace" font-size="{round(size * 0.068)}">{center_sub}</text>'
        )
    return head + body + text + "</svg>"


# ============================================================================
# Bands, grades and formatting
# ============================================================================

# Higher-is-better colour bands, tuned for the dark presentation. `soft`/`edge`
# are the translucent fill/border used by chips; `g1`/`g2` drive the bar and
# ring gradients.
_BANDS = {
    "green": {"key": "green", "label": "Good", "fg": "#34d399", "g1": "#34d399", "g2": "#22d3ee",
              "soft": "rgba(52,211,153,.12)", "edge": "rgba(52,211,153,.38)"},
    "yellow": {"key": "yellow", "label": "Needs Improvement", "fg": "#fbbf24", "g1": "#f59e0b", "g2": "#fbbf24",
               "soft": "rgba(251,191,36,.13)", "edge": "rgba(251,191,36,.40)"},
    "orange": {"key": "orange", "label": "Important Issue", "fg": "#fb923c", "g1": "#f97316", "g2": "#fbbf24",
               "soft": "rgba(251,146,60,.13)", "edge": "rgba(251,146,60,.42)"},
    "red": {"key": "red", "label": "Critical Issue", "fg": "#fb5b6f", "g1": "#fb5b6f", "g2": "#fb923c",
            "soft": "rgba(251,91,111,.14)", "edge": "rgba(251,91,111,.42)"},
    "gray": {"key": "gray", "label": "Not Verified", "fg": "#7f8bad", "g1": "#3a4463", "g2": "#55607d",
             "soft": "rgba(148,178,255,.07)", "edge": "rgba(148,178,255,.20)"},
}


def _band(score: Optional[int], applicable: bool = True) -> Dict[str, str]:
    """Higher-is-better colour band for the premium scorecard (0-100)."""
    if not applicable:
        return {**_BANDS["gray"], "label": "Not Applicable"}
    if score is None:
        return dict(_BANDS["gray"])
    if score >= 85:
        return dict(_BANDS["green"])
    if score >= 70:
        return dict(_BANDS["yellow"])
    if score >= 50:
        return dict(_BANDS["orange"])
    return dict(_BANDS["red"])


def _grade(score: Optional[int]) -> str:
    """A letter grade that is nothing more than a restatement of the measured
    score - no benchmark, industry average or peer comparison is implied,
    because the engine has no data to support one."""
    if score is None:
        return ""
    for floor, letter in (
        (95, "A+"), (90, "A"), (85, "A−"), (80, "B+"), (75, "B"), (70, "B−"),
        (65, "C+"), (60, "C"), (55, "C−"), (50, "D+"), (40, "D"), (0, "F"),
    ):
        if score >= floor:
            return letter
    return "F"


_BADGE_CLASS = {"high": "critical", "medium": "high", "low": "medium"}


def _fmt_bool(v: Any, yes: str = "Yes", no: str = "No", unknown: str = "Not measured") -> str:
    if v is True:
        return yes
    if v is False:
        return no
    return unknown


def _evidence_lines(ev: Dict[str, Any]) -> List[str]:
    """Flat "key: value" evidence lines (kept for callers/tests that expect the
    older shape). `_evidence_rows` renders the same data as label/value pairs."""
    return [f"{r['k']}: {r['v']}" for r in _evidence_rows(ev)]


def _evidence_rows(ev: Dict[str, Any], limit: int = 6) -> List[Dict[str, str]]:
    """Label/value pairs straight from the finding's own evidence dict. Only
    what the check actually recorded - never padded out."""
    out: List[Dict[str, str]] = []
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
            value = ", ".join(str(i)[:110] for i in items)
            if len(val) > 4:
                value += f" (+{len(val) - 4} more)"
        elif isinstance(val, dict):
            continue
        elif isinstance(val, bool):
            # Raw Python True/False reads as a bug in a client document.
            value = "Yes" if val else "No"
        else:
            value = str(val)[:240]
        out.append({"k": label, "v": value})
        if len(out) >= limit:
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
        "severity_badge": SEVERITY_BADGE.get(sev, "LOW"),
        "badge_class": _BADGE_CLASS.get(sev, "low"),
        "title": f.title,
        "detail": f.detail,
        "evidence_lines": _evidence_lines(f.evidence),
        "evidence_rows": _evidence_rows(f.evidence),
        "recommendation": f.recommendation,
        # Prefer the explanation written for this specific defect; fall back to
        # the category-level one only when there is no code-specific entry.
        "why_it_matters": WHY_BY_CODE.get(f.code) or AUDIT_CATEGORY_WHY.get(cat, ""),
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


# ============================================================================
# Verified-signal panels - real measurements only, with an explicit
# "Not Verified" / "Not Available" + reason wherever a value is missing.
# ============================================================================


def _sig(label: str, value: Any, *, why: str = "", na_text: str = "Not Available") -> Dict[str, Any]:
    if value in (None, "", []):
        return {"label": label, "value": na_text, "na": True, "why": why}
    return {"label": label, "value": str(value), "na": False, "why": why}


def _headline_signals(
    tech: Dict[str, Any], perf: Dict[str, Any], extra: Dict[str, Any], checks: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """The measurements a reader wants on the analytics page - all real."""
    sec = extra.get("security") or {}
    onp = extra.get("onpage") or {}
    out: List[Dict[str, Any]] = []

    out.append(_sig("HTTP status", tech.get("http_status")))
    out.append(_sig("HTTPS", _fmt_bool(tech.get("is_https"), "Enabled", "Not enabled", "Not measured")))
    out.append(_sig(
        "Homepage response time",
        f"{tech['response_ms']} ms" if tech.get("response_ms") is not None else None,
        why="Single server-side measurement from the machine that ran this audit — not a full performance profile.",
    ))
    out.append(_sig("Pages crawled", tech.get("pages_crawled")))
    out.append(_sig("Indexable", "Yes" if not (tech.get("meta_robots") or "").lower().count("noindex") else "No — noindex present"))
    out.append(_sig("XML sitemap", _fmt_bool(tech.get("sitemap_found"), "Found", "Not found", "Not measured")))
    out.append(_sig("robots.txt", _fmt_bool(tech.get("robots_txt_found"), "Found", "Not found", "Not measured")))
    out.append(_sig(
        "Internal links checked",
        f"{tech['links_checked']} · {len(tech.get('broken_links') or [])} broken" if tech.get("links_checked") else None,
    ))
    if tech.get("alt_coverage") is not None:
        out.append(_sig("Image alt coverage", f"{int(tech['alt_coverage'] * 100)}% of {tech.get('images_total', 0)} images"))
    else:
        out.append(_sig("Image alt coverage", None, why="No images were found on the crawled pages."))
    out.append(_sig("Structured data types", ", ".join(onp.get("schema_types_found") or []) or None,
                    why="No JSON-LD schema types were found on the crawled pages." if not onp.get("schema_types_found") else ""))
    out.append(_sig("Security headers measured", _fmt_bool(sec.get("headers_measured"), "Yes", "No", "Not measured")))
    out.append(_sig("Page HTML size", f"{round((tech.get('page_bytes') or 0) / 1024)} KB" if tech.get("page_bytes") else None))

    if perf.get("measured"):
        out.append(_sig("Google PageSpeed score", f"{perf.get('performance_score')}/100 ({perf.get('strategy')})"))
        out.append(_sig("Largest Contentful Paint", f"{perf['lcp_s']} s" if perf.get("lcp_s") is not None else None))
    else:
        out.append(_sig(
            "Core Web Vitals (LCP / CLS / INP)", None, na_text="Not Verified",
            why="Requires a Google PageSpeed Insights API key, which is not configured for this audit. "
                "These values are never estimated.",
        ))
    out.append(_sig(
        "Backlinks / referring domains / domain authority", None, na_text="Not Verified",
        why="Requires a paid third-party index (Ahrefs, Moz, Majestic, SEMrush). Never estimated or fabricated.",
    ))
    out.append(_sig(
        "Organic traffic / keyword rankings", None, na_text="Not Verified",
        why="Requires Search Console access or a paid rank-tracking source. Never estimated or fabricated.",
    ))
    return out


def _category_signals(
    key: str, tech: Dict[str, Any], mob: Dict[str, Any], conv: Dict[str, Any], extra: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Per-category technical context, for the developer reading the report.
    Everything here is a value the engine actually recorded."""
    sec = extra.get("security") or {}
    a11y = extra.get("accessibility") or {}
    onp = extra.get("onpage") or {}
    offp = extra.get("offpage") or {}
    pex = extra.get("performance_extra") or {}
    loc = extra.get("local_seo") or {}

    if key == "technical":
        return [
            _sig("Final URL", tech.get("final_url")),
            _sig("Redirect hops", tech.get("redirect_count")),
            _sig("Canonical URL", tech.get("canonical"), why="No canonical link element was found." if not tech.get("canonical") else ""),
            _sig("Meta robots", tech.get("meta_robots"), why="No meta robots directive was present (default: index, follow)." if not tech.get("meta_robots") else ""),
            _sig("Sitemap URL", tech.get("sitemap_url")),
            _sig("Broken internal links", len(tech.get("broken_links") or []) if tech.get("links_checked") else None),
        ]
    if key == "onpage":
        return [
            _sig("Title", tech.get("title"), why=f"{tech.get('title_length', 0)} characters" if tech.get("title") else "No <title> element was found."),
            _sig("Meta description", tech.get("meta_description"), why=f"{tech.get('meta_description_length', 0)} characters" if tech.get("meta_description") else "No meta description was found."),
            _sig("H1", ", ".join(tech.get("h1") or []) or None, why=f"{tech.get('h1_count', 0)} H1 element(s) on the homepage"),
            _sig("Open Graph tags", ", ".join(onp.get("open_graph_tags") or []) or None),
            _sig("Twitter/X card tags", ", ".join(onp.get("twitter_card_tags") or []) or None),
            _sig("Declared language", tech.get("lang")),
        ]
    if key == "local_seo":
        if not loc:
            return []
        return [
            _sig("LocalBusiness/Organization schema", _fmt_bool(loc.get("local_business_schema"), "Present", "Not found")),
            _sig("Schema contains a postal address", _fmt_bool(loc.get("schema_has_address"), "Yes", "No")),
            _sig("Address published on site", _fmt_bool(loc.get("address_signal"), "Yes", "Not found")),
            _sig("Map embed or Google Business Profile link", _fmt_bool(loc.get("map_or_gbp_link"), "Present", "Not found")),
            _sig("Service-area content", _fmt_bool(loc.get("service_area_signal"), "Present", "Not found")),
            _sig("Opening hours", _fmt_bool(loc.get("opening_hours_signal"), "Published", "Not found")),
        ]
    if key == "offpage":
        return [
            _sig("Social profiles linked from the site", ", ".join(offp.get("social_profiles_linked") or []) or None),
            _sig("sameAs entries in structured data", ", ".join(offp.get("structured_data_sameas") or []) or None),
            _sig("External domains referenced", offp.get("external_domains_referenced_count")),
            _sig("Backlink count", None, na_text="Not Verified", why=(offp.get("backlinks") or {}).get("reason", "")),
            _sig("Referring domains", None, na_text="Not Verified", why=(offp.get("referring_domains") or {}).get("reason", "")),
            _sig("Domain authority", None, na_text="Not Verified", why=(offp.get("domain_authority") or {}).get("reason", "")),
        ]
    if key == "performance":
        return [
            _sig("Response time", f"{tech['response_ms']} ms" if tech.get("response_ms") is not None else None),
            _sig("HTML size", f"{round((tech.get('page_bytes') or 0) / 1024)} KB" if tech.get("page_bytes") else None),
            _sig("Scripts on homepage", tech.get("script_count")),
            _sig("Render-blocking scripts", pex.get("render_blocking_scripts")),
            _sig("Stylesheets", pex.get("stylesheet_count")),
            _sig("Content-Encoding", pex.get("content_encoding"), why="No compression header was returned." if not pex.get("content_encoding") else ""),
            _sig("Cache-Control", pex.get("cache_control")),
        ]
    if key == "accessibility":
        return [
            _sig("Language declared", _fmt_bool(a11y.get("lang_declared"), "Yes", "No")),
            _sig("<main> landmark", _fmt_bool(a11y.get("has_main_landmark"), "Present", "Missing")),
            _sig("<nav> landmark", _fmt_bool(a11y.get("has_nav_landmark"), "Present", "Missing")),
            _sig("Skip link", _fmt_bool(a11y.get("has_skip_link"), "Present", "Missing")),
            _sig("Unlabelled form inputs", f"{a11y.get('unlabelled_form_inputs')} of {a11y.get('form_inputs_checked')}" if a11y.get("form_inputs_checked") else None),
            _sig("Links with no accessible text", a11y.get("empty_links")),
            _sig("Colour contrast", None, na_text="Not Verified", why=a11y.get("contrast_note", "")),
        ]
    if key == "security":
        return [
            _sig("HTTPS", _fmt_bool(sec.get("is_https"), "Enabled", "Not enabled")),
            _sig("Strict-Transport-Security", _fmt_bool(sec.get("hsts_present"), "Present", "Missing")),
            _sig("Content-Security-Policy", _fmt_bool(sec.get("csp_present"), "Present", "Missing")),
            _sig("X-Content-Type-Options", sec.get("x_content_type_options")),
            _sig("X-Frame-Options", sec.get("x_frame_options")),
            _sig("Referrer-Policy", _fmt_bool(sec.get("referrer_policy_present"), "Present", "Missing")),
            _sig("Permissions-Policy", _fmt_bool(sec.get("permissions_policy_present"), "Present", "Missing")),
            _sig("Mixed content items", tech.get("mixed_content_count")),
        ]
    if key == "ux_conversion":
        return [
            _sig("Mobile viewport", mob.get("viewport"), why="No viewport meta tag was found." if not mob.get("viewport") else ""),
            _sig("Tap-to-call on homepage", _fmt_bool(mob.get("tap_to_call_on_homepage"), "Present", "Not found")),
            _sig("Mobile navigation pattern", _fmt_bool(mob.get("mobile_menu_detected"), "Detected", "Not detected")),
            _sig("Contact form", _fmt_bool(conv.get("has_contact_form"), "Present", "Not found")),
            _sig("Booking CTA", _fmt_bool(conv.get("has_booking_cta"), "Present", "Not found")),
            _sig("Strong CTAs counted", conv.get("strong_cta_count")),
        ]
    return []


# Why each specific finding matters, in plain language. Without this the
# report repeats one category-level sentence under every finding in that
# category, which reads as filler. These are explanations of a defect's
# consequence - standard, checkable web/SEO behaviour - and deliberately
# contain no measured claim: no traffic, ranking, conversion or revenue
# figure appears here, because the engine cannot measure any of those.
# Anything not listed falls back to the category-level explanation.
WHY_BY_CODE: Dict[str, str] = {
    # --- technical -------------------------------------------------------
    "noindex": "A noindex directive tells search engines to drop the page from their index entirely. "
               "While it is present, the page cannot rank for anything, no matter how good it is.",
    "missing_sitemap": "An XML sitemap is how a site tells search engines which URLs exist and are worth "
                       "crawling. Without one, discovery relies purely on internal links, so newer or "
                       "deeply nested pages can be found late or missed.",
    "missing_robots": "robots.txt is the first file a crawler requests. Without it, crawlers get no "
                      "guidance on which areas to skip, and the conventional place to point at the "
                      "sitemap is missing.",
    "broken_internal_links": "Broken internal links send visitors and crawlers to dead ends, waste crawl "
                             "budget, and break the flow of link equity between pages.",
    "long_redirect_chain": "Each redirect hop adds latency for the visitor and dilutes the signal passed "
                           "to the final URL. Long chains are also a common source of redirect loops.",
    # --- on-page ---------------------------------------------------------
    "missing_title": "The title tag is the headline of the search result and the browser tab. With none, "
                     "search engines invent one from page content, and the site loses its single "
                     "strongest on-page relevance signal.",
    "title_too_short": "A very short title wastes the most valuable text a search result can show and "
                       "usually omits the service and location a searcher typed.",
    "title_too_long": "Titles beyond roughly 60 characters get truncated in search results, so the end "
                      "of the message - often the brand or location - is cut off.",
    "missing_meta_description": "Without a meta description, search engines assemble a snippet from "
                                "whatever text they find, which often reads awkwardly and rarely makes "
                                "the case for clicking.",
    "meta_description_short": "A very short description leaves most of the available snippet space "
                              "unused, giving searchers less reason to choose this result.",
    "missing_h1": "The H1 is the page's main heading. Without one, both search engines and screen reader "
                  "users lack a clear statement of what the page is about.",
    "multiple_h1": "Several H1s give no single clear subject for the page and make the heading outline "
                   "ambiguous for assistive technology.",
    "missing_canonical": "Without a canonical URL, the same content reachable at several addresses "
                         "(with/without a trailing slash, with tracking parameters) can be treated as "
                         "duplicates, splitting ranking signals between them.",
    "onpage_missing_open_graph": "Open Graph tags control the title, description and image shown when the "
                                 "page is shared on social platforms or messaging apps. Without them the "
                                 "preview is assembled at random, or is blank.",
    "onpage_missing_twitter_card": "Without a card tag, links shared on X/Twitter render as a plain URL "
                                   "rather than a rich preview.",
    "onpage_duplicate_titles": "Pages sharing a title look interchangeable to search engines, which makes "
                               "it harder for the right page to be selected for a given query.",
    "onpage_duplicate_meta_description": "Duplicate descriptions produce identical-looking search "
                                         "results, so nothing distinguishes one page from another.",
    "generic_value_proposition": "A heading like “Welcome” or “Home” tells neither a visitor nor a search "
                                 "engine what the business actually does.",
    "no_heading_structure": "Headings are the outline of the page. With none below the top level, the "
                            "content has no machine-readable structure and is harder to scan.",
    "very_thin_homepage": "A homepage with very little text gives search engines almost nothing to "
                          "understand the business by, and gives visitors little reason to stay.",
    "thin_homepage": "There is limited content for search engines to assess relevance from, and limited "
                     "information for a visitor deciding whether to enquire.",
    "services_not_clear": "If the services offered are not stated in plain text, the site cannot match "
                          "the searches people actually type.",
    "no_service_area": "Without a stated service area, both visitors and search engines have to guess "
                       "where the business operates.",
    # --- local SEO -------------------------------------------------------
    "local_no_business_schema": "LocalBusiness/Organization JSON-LD is how a search engine confirms a "
                                "business's name, address and category as structured facts rather than "
                                "inferring them from page text. It underpins map and local results.",
    "local_no_address_signal": "A published address is a core local ranking and trust signal, and is what "
                               "directories and search engines match against.",
    "local_address_not_structured": "An address that appears only as visible text has to be parsed out of "
                                    "prose. In structured data it is unambiguous.",
    "local_no_map_or_gbp_link": "A map embed or Google Business Profile link connects the website to the "
                                "business's map listing, which is where local searchers usually arrive.",
    "local_no_service_area_content": "Without pages or sections naming the areas served, there is nothing "
                                     "for location-specific searches to match.",
    "local_no_opening_hours": "Opening hours are among the first things a local searcher looks for, and "
                              "are shown directly in map results when published.",
    "local_no_reviews_or_testimonials": "Social proof is a decisive factor for local purchases, and "
                                        "review content is a visible trust signal on the page itself.",
    "local_reviews_not_structured": "Reviews marked up as Review/AggregateRating can qualify for "
                                    "star-rating rich results; as plain text they cannot.",
    "local_name_mismatch": "When the business name in structured data differs from the name on the page, "
                           "search engines get conflicting information about which entity this is.",
    # --- off-page --------------------------------------------------------
    "offpage_no_social_profiles": "Linked social profiles are one of the few verifiable off-site signals "
                                  "a website can publish about itself, and they give visitors another "
                                  "way to check the business is real and active.",
    "offpage_sameas_not_structured": "Declaring profile URLs as sameAs in structured data is what lets a "
                                     "search engine tie those accounts to this business as one entity, "
                                     "rather than treating them as unrelated links.",
    "no_social_presence_linked": "With no social presence linked from the site, visitors have no "
                                 "secondary way to verify the business is active.",
    # --- performance -----------------------------------------------------
    "slow_response": "Server response time sits in front of everything else: nothing can render until the "
                     "first byte arrives, so it sets the floor for every other speed metric.",
    "heavy_page": "A large HTML document takes longer to download and parse, which delays the point at "
                  "which a visitor sees anything - most noticeably on mobile connections.",
    "many_scripts": "Every script must be fetched, parsed and executed, competing with rendering for the "
                    "main thread and delaying interactivity.",
    "perf_render_blocking_scripts": "Scripts in the head without defer or async stop the page rendering "
                                    "until they finish loading, leaving the visitor on a blank screen.",
    "perf_no_compression": "Serving uncompressed text means sending several times more bytes than "
                           "necessary for the same page.",
    "perf_no_cache_headers": "Without cache headers, returning visitors re-download assets that have not "
                             "changed, making repeat visits slower than they need to be.",
    "pagespeed_low": "This is Google's own measurement of the page experience, and page experience is an "
                     "input to how the page is ranked as well as to whether visitors stay.",
    # --- accessibility ---------------------------------------------------
    "missing_lang": "Without a declared language, screen readers may use the wrong pronunciation rules, "
                    "making the page hard or impossible to follow by ear.",
    "low_alt_coverage": "Images without alt text are invisible to screen reader users and give search "
                        "engines nothing to index them by.",
    "a11y_no_main_landmark": "A <main> landmark is what lets keyboard and screen reader users jump "
                             "straight to the content instead of tabbing through the whole header.",
    "a11y_unlabelled_form_inputs": "An input with no label is announced as an unnamed field, so a screen "
                                   "reader user cannot tell what to type into it.",
    "a11y_empty_links": "A link with no accessible text is announced only as “link”, giving no indication "
                        "of where it goes.",
    "a11y_heading_order_skipped": "Skipped heading levels break the document outline that assistive "
                                  "technology uses to navigate a page.",
    # --- security --------------------------------------------------------
    "no_https": "Without HTTPS, everything sent between visitor and site - including anything typed into "
                "a form - travels in the clear, and browsers actively mark the site as Not Secure.",
    "mixed_content": "Loading HTTP resources on an HTTPS page undermines the encryption and causes "
                     "browsers to block those resources or warn the visitor.",
    "security_hsts_missing": "Without HSTS, a visitor's first request can still be made over plain HTTP "
                             "and intercepted before the redirect to HTTPS happens.",
    "security_csp_missing": "A Content-Security-Policy is the strongest browser-level defence against "
                            "cross-site scripting and unauthorised resource loading.",
    "security_frame_protection_missing": "Without frame protection, the site can be embedded invisibly in "
                                         "another page and used to trick visitors into clicking things "
                                         "they cannot see.",
    "security_xcto_missing": "Without nosniff, a browser may guess a file's type and execute something "
                             "that was never meant to run as script.",
    "security_referrer_policy_missing": "Without a referrer policy, full URLs - which can contain private "
                                        "identifiers - are sent to every third-party resource the page "
                                        "loads.",
    "security_server_header_discloses_version": "Publishing exact software versions tells an attacker "
                                                "precisely which known vulnerabilities to try first.",
    # --- UX & conversion --------------------------------------------------
    "missing_viewport": "Without a viewport tag, mobile browsers render the desktop layout zoomed out, so "
                        "text is tiny and buttons are hard to hit.",
    "viewport_not_responsive": "A viewport that is not set to the device width prevents the layout from "
                               "adapting to the screen it is being viewed on.",
    "zoom_disabled": "Blocking pinch-to-zoom removes the main way low-vision visitors make text readable.",
    "fixed_width_layout": "Fixed widths wider than a phone screen force horizontal scrolling, which makes "
                          "the page awkward to read and use on mobile.",
    "small_mobile_text": "Text below roughly 12px is difficult to read on a phone without zooming.",
    "no_mobile_tap_to_call": "On a phone, a number that is not a tel: link has to be memorised or copied "
                             "by hand instead of tapped, and most people will not bother.",
    "legacy_plugin_content": "Plugin-based content does not run in any modern browser, so that part of "
                             "the page is simply blank for every visitor.",
    "no_mobile_menu": "Without a mobile navigation pattern, the menu is often unusable at phone widths, "
                      "cutting visitors off from the rest of the site.",
    "minimal_navigation": "With very few navigation links, visitors have no obvious route from the "
                          "homepage to the information they came for.",
    "no_primary_cta_above_fold": "If there is no clear action near the top of the page, the visitors who "
                                 "are ready to act have to hunt for how to do it.",
    "no_phone_cta": "A phone number that is not a clickable link adds friction at exactly the moment "
                    "someone has decided to get in touch.",
    "no_phone_on_site": "With no phone number anywhere on the site, an entire category of enquiry - the "
                        "person who wants to speak to someone now - has nowhere to go.",
    "phone_not_on_homepage": "A number only reachable via a subpage is missed by visitors who never leave "
                             "the homepage.",
    "no_contact_form": "A form captures enquiries from people who will not phone and do not want to open "
                       "an email client - typically the majority of web visitors.",
    "no_contact_page": "A contact page is the page visitors look for by default when they want to get in "
                       "touch, and the one search engines expect to find.",
    "no_booking_cta": "Without a booking option, every appointment has to be arranged by a back-and-forth "
                      "the visitor has to start.",
    "no_quote_cta": "A quote request is the natural next step for a service business, and its absence "
                    "leaves interested visitors with no defined action.",
    "no_email_cta": "Without a visible email option, visitors who prefer writing have no route to make "
                    "contact.",
    "no_email_on_site": "No published email address means one of the standard ways to reach a business is "
                        "unavailable.",
    "weak_cta_language": "Vague prompts like “click here” or “submit” do not tell a visitor what will "
                         "happen, and convert less well than explicit actions.",
    "no_testimonials": "Social proof from previous customers is one of the strongest influences on "
                       "whether a new visitor decides to make contact.",
    "reviews_not_structured": "Reviews marked up as structured data can appear as star ratings in search "
                              "results; as plain text they cannot.",
    "no_credentials": "Licences, insurance, accreditations and guarantees are what reassure a visitor "
                      "that the business is legitimate and accountable.",
    "no_portfolio": "Examples of previous work let a visitor judge quality for themselves rather than "
                    "taking the site's word for it.",
    "no_about_page": "An about page is where a visitor checks who they would actually be dealing with.",
    "no_address": "A published address is a basic trust signal - its absence makes a business look harder "
                  "to hold accountable.",
    "no_opening_hours": "Without opening hours, a visitor cannot tell whether contacting the business now "
                        "is worthwhile.",
    "contact_hard_to_find": "If contact details are buried, interested visitors give up before finding "
                            "them.",
    "no_website_detected": "With no website, the business is invisible to everyone who searches before "
                           "they buy, and has no page of its own to send anyone to.",
    "social_profile_only": "A social profile is rented space: its layout, reach and continued existence "
                           "are controlled by the platform, not by the business.",
}


_CATEGORY_DISCLOSURE = {
    "offpage": "backlink count, referring domains and domain-authority-style scores require a paid "
               "third-party index (e.g. Ahrefs, Moz, Majestic, SEMrush). None is configured for this "
               "audit, so none of that is estimated or fabricated here.",
    "accessibility": "colour contrast requires a rendered page with computed styles and cannot be "
                     "measured reliably from static HTML/CSS, so it is reported as not verified "
                     "rather than guessed.",
    "performance": "Core Web Vitals (LCP, CLS, INP) come from the Google PageSpeed Insights API. "
                   "Without an API key configured, only a single server-side response-time "
                   "measurement is available and no lab or field vitals are shown.",
    "ux_conversion": "mobile findings are derived from the page's own markup and inline CSS, not "
                     "from a rendered phone browser; external stylesheets were not downloaded.",
}


# ============================================================================
# Render
# ============================================================================


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
        sev = p.get("severity") if p.get("severity") in SEVERITY_ORDER else "low"
        item = dict(p)
        item["severity"] = sev
        item["severity_badge"] = SEVERITY_BADGE.get(sev, "LOW")
        item["badge_class"] = _BADGE_CLASS.get(sev, "low")
        item["recommendation"] = rec_by_code.get(p.get("code"), "")
        item["evidence_rows"] = _evidence_rows(p.get("evidence") or {})
        enriched.append(item)

    tech = audit.get("technical") or {}
    mob = audit.get("mobile") or {}
    conv = audit.get("conversion") or {}
    perf = tech.get("pagespeed") or {}
    extra = extra_facts or {}

    # ---- appendix: what was measured --------------------------------------
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

    priorities_ctx = []
    for p in (priorities or []):
        sev = p.get("severity") if p.get("severity") in SEVERITY_ORDER else "low"
        priorities_ctx.append({
            **p,
            "severity_label": SEVERITY_LABEL.get(sev, "Note"),
            "severity_badge": SEVERITY_BADGE.get(sev, "LOW"),
            "badge_class": _BADGE_CLASS.get(sev, "low"),
        })

    # ---- per-category "Issues & Recommendations" sections -------------------
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
            cat_findings = by_cat.get(c, [])
            worst = min((SEVERITY_ORDER.get(f["severity"], 2) for f in cat_findings), default=3)
            category_sections.append({
                "key": c,
                "number": f"{i + 1:02d}",
                "label": AUDIT_CATEGORY_LABELS.get(c, c.title()),
                "icon": CATEGORY_ICON.get(c, "•"),
                "why_it_matters": AUDIT_CATEGORY_WHY.get(c, ""),
                "applicable": applicable,
                "not_applicable_reason": row.get("not_applicable_reason", ""),
                "score": score,
                "band": _band(score, applicable),
                "findings": cat_findings,
                "count_class": {0: "critical", 1: "high", 2: "medium"}.get(worst, "pass"),
                "passed_checks": [x for x in checks_here if x["status"] == "pass"],
                "not_verified_checks": [x for x in checks_here if x["status"] == "not_verified"],
                "signals": [s for s in _category_signals(c, tech, mob, conv, extra)] if applicable else [],
                "disclosure": _CATEGORY_DISCLOSURE.get(c, ""),
            })

    scorecard_ctx: Dict[str, Any] = {}
    checks_ctx: Dict[str, Any] = {
        "passed_count": 0, "warning_count": 0, "failed_count": 0,
        "not_verified_count": 0, "not_applicable_count": 0, "total_checked": 0,
        "total_catalogued": 0,
    }
    priority_counts = {"P1": 0, "P2": 0, "P3": 0}
    donut_severity = donut_status = donut_priority = ""
    ring_overall = ""
    overall_band = _band(None)
    grade = ""
    total_issues = 0
    findings_per_category: List[Dict[str, Any]] = []
    signals: List[Dict[str, Any]] = []
    check_bar: Dict[str, Any] = {"total": 0, "pass_pct": 0, "warn_pct": 0, "fail_pct": 0}

    if scorecard:
        cats = []
        for row in scorecard.get("categories", []):
            band = _band(row.get("score"), row.get("applicable", True))
            cats.append({**row, "band": band, "icon": CATEGORY_ICON.get(row.get("category"), "•")})
        scorecard_ctx = {**scorecard, "categories": cats}
        checks_ctx = {**checks_ctx, **scorecard.get("checks", {})}
        overall_band = _band(scorecard.get("overall_score"))
        grade = _grade(scorecard.get("overall_score"))

        for f in (list(legacy_findings or []) + list(extra_findings or [])):
            if f.deduction > 0:
                priority_counts[priority_for(f)] = priority_counts.get(priority_for(f), 0) + 1

        sev_counts = scorecard.get("severity_counts", {})
        total_issues = sum(sev_counts.get(k, 0) for k in ("high", "medium", "low"))

        ring_overall = _svg_ring(
            scorecard.get("overall_score"), size=188,
            g1=overall_band["g1"], g2=overall_band["g2"], uid="overallRing",
        )
        donut_severity = _svg_donut(
            [
                {"value": sev_counts.get("high", 0), "color": "#fb5b6f"},
                {"value": sev_counts.get("medium", 0), "color": "#fb923c"},
                {"value": sev_counts.get("low", 0), "color": "#fbbf24"},
            ],
            center_sub="ISSUES",
        )
        donut_status = _svg_donut(
            [
                {"value": checks_ctx.get("passed_count", 0), "color": "#34d399"},
                {"value": checks_ctx.get("warning_count", 0), "color": "#fbbf24"},
                {"value": checks_ctx.get("failed_count", 0), "color": "#fb5b6f"},
                {"value": checks_ctx.get("not_verified_count", 0) + checks_ctx.get("not_applicable_count", 0), "color": "#55607d"},
            ],
            center_sub="CHECKS",
        )
        donut_priority = _svg_donut(
            [
                {"value": priority_counts.get("P1", 0), "color": "#fb5b6f"},
                {"value": priority_counts.get("P2", 0), "color": "#fb923c"},
                {"value": priority_counts.get("P3", 0), "color": "#3b82f6"},
            ],
            center_sub="ACTIONS",
        )

        max_count = max((len(by_cat.get(c, [])) for c in AUDIT_CATEGORIES), default=0)
        for c in AUDIT_CATEGORIES:
            n = len(by_cat.get(c, []))
            row = cat_row_by_key.get(c, {})
            if row.get("applicable", True) is False:
                continue
            findings_per_category.append({
                "label": AUDIT_CATEGORY_LABELS.get(c, c.title()),
                "count": n,
                "pct": round(100 * n / max_count) if max_count else 0,
                "g1": "#fb5b6f" if n and n >= max(1, max_count * 0.66) else ("#fb923c" if n else "#34d399"),
                "g2": "#fb923c" if n else "#22d3ee",
            })

        signals = _headline_signals(tech, perf, extra, checks_ctx)

        # Passed / warning / failed as one stacked bar, over the checks that
        # could actually be evaluated (N/V and N/A are excluded from the bar
        # and shown as a separate count, since they are neither).
        evaluated = (
            checks_ctx.get("passed_count", 0)
            + checks_ctx.get("warning_count", 0)
            + checks_ctx.get("failed_count", 0)
        )
        check_bar = {
            "total": evaluated,
            "pass_pct": round(100 * checks_ctx.get("passed_count", 0) / evaluated, 1) if evaluated else 0,
            "warn_pct": round(100 * checks_ctx.get("warning_count", 0) / evaluated, 1) if evaluated else 0,
            "fail_pct": round(100 * checks_ctx.get("failed_count", 0) / evaluated, 1) if evaluated else 0,
        }

    # ---- cover metadata: only fields that actually have a value -------------
    cover_meta: List[Dict[str, str]] = [
        {"label": "Audit date", "value": dt.datetime.now().strftime("%d %b %Y")},
    ]
    if tech.get("pages_crawled"):
        cover_meta.append({"label": "Pages scanned", "value": str(tech["pages_crawled"])})
    if checks_ctx.get("total_catalogued"):
        cover_meta.append({"label": "Checks run", "value": str(checks_ctx["total_catalogued"])})
    if business.get("location"):
        cover_meta.append({"label": "Location", "value": str(business["location"])})
    if business.get("category"):
        cover_meta.append({"label": "Category", "value": str(business["category"])})
    if generator:
        cover_meta.append({"label": "Prepared by", "value": generator})

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
        cover_meta=cover_meta,
        generated_at=dt.datetime.now().strftime("%d %b %Y at %H:%M"),
        generator=generator,
        scorecard=scorecard_ctx,
        checks=checks_ctx,
        check_bar=check_bar,
        findings=findings_ctx,
        findings_per_category=findings_per_category,
        signals=signals,
        category_sections=category_sections,
        priorities=priorities_ctx,
        executive_summary=executive_summary or {},
        overall_band=overall_band,
        grade=grade,
        total_issues=total_issues,
        priority_counts=priority_counts,
        ring_overall=ring_overall,
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
