// CSV / XLSX / reports.zip export. Ported from backend/app/core/exporter.py.
// The original also joins WhatsApp/email/LinkedIn outreach drafts into these
// rows; this deployment does not generate those drafts (see README —
// outreach messaging has no UI in this app and was intentionally left out
// of the port), so those columns are always blank here rather than absent,
// which keeps the exported file's column layout identical either way.
import ExcelJS from "exceljs";
import { zipSync, strToU8 } from "fflate";

const TOP_ISSUE_RANKS = 5;
const TOP_ISSUE_COLUMNS: string[] = [];
for (let i = 1; i <= TOP_ISSUE_RANKS; i++) {
  for (const suffix of ["", "_category", "_severity", "_fix"]) TOP_ISSUE_COLUMNS.push(`top_issue_${i}${suffix}`);
}

export const ENRICHMENT_COLUMNS: string[] = [
  "website_status", "website_final", "website_identity_confidence", "website_source",
  "email_1", "email_1_source", "email_1_status", "email_2", "email_2_source", "email_2_status",
  "phone_raw_original", "phone_normalized", "phone_country", "phone_type", "phone_status",
  "whatsapp_status", "whatsapp_reason", "whatsapp_url",
  "linkedin_url", "linkedin_status",
  "website_score", "opportunity_tier", "lead_tier",
  "problems", "recommendations",
  ...TOP_ISSUE_COLUMNS,
  "contact_channel", "contact_channel_reason",
  "whatsapp_message", "whatsapp_draft_url",
  "email_subject", "email_message", "email_draft_url",
  "linkedin_message", "call_notes",
  "audit_report_path", "audit_status", "audit_error", "processed_at",
];

const CONTACT_CHANNEL_DISPLAY: Record<string, string> = {
  whatsapp: "WHATSAPP", email: "EMAIL", linkedin: "LINKEDIN", phone: "PHONE", none: "SKIP", "": "SKIP",
  website_contact: "WEBSITE_CONTACT",
};

export const COLUMN_DOCS: Record<string, string> = {
  website_status: "valid / redirected / unavailable / blocked / mismatch / not_found / not_a_website (social or directory profile) / no_website (verified none found).",
  website_identity_confidence: "0-1 confidence that the site belongs to this exact business, from domain, title, phone and address matching.",
  website_source: "csv = supplied in your file; discovered = found by domain guess and confirmed by identity matching; none.",
  email_1: "A public address found on the business's own website. Never guessed or constructed.",
  email_1_source: "The exact page URL the address was found on.",
  email_1_status: "valid_public / mx_valid / domain_valid / syntax_valid / risky / invalid / unknown. Mailbox deliverability is never claimed.",
  phone_normalized: "E.164 format. Empty when the number could not be parsed with confidence.",
  phone_status: "valid / possible / invalid / unparseable / ambiguous_region / unavailable.",
  whatsapp_status: "confirmed_on_website (a WhatsApp link for this number is published on their site) / usable_unverified / unlikely (landline) / invalid_number / no_phone.",
  whatsapp_url: "wa.me click-to-chat link with the message pre-filled. Nothing is sent automatically - you open and send it yourself.",
  linkedin_url: "The business's own LinkedIn company page, found as a link on their website. Never a guess and never a personal employee profile.",
  linkedin_status: "not_checked / found / not_found.",
  website_score: "0-100 opportunity score. HIGHER means more measured room to improve.",
  opportunity_tier: "Very High 90+, High 75-89, Good 60-74, Moderate 40-59, Low 0-39.",
  lead_tier: "A+ / A / B / C / D combining opportunity, website validity, contact availability and whether a strong specific problem exists.",
  problems: "The detected problems, each backed by an actual measurement.",
  top_issue_1: "The single highest-priority issue from the premium audit's Top 5 priorities. See top_issue_1_category / _severity / _fix for the rest of that issue's record, and top_issue_2..5 for the next four.",
  contact_channel: "WHATSAPP / EMAIL / LINKEDIN / PHONE / SKIP, in that priority order.",
  whatsapp_message: "Draft only. Personalised from this business's own audit findings.",
  email_draft_url: "mailto: link with subject and body pre-filled. Not sent automatically.",
  linkedin_message: "Draft only, for pasting into a LinkedIn message manually.",
  call_notes: "Opening line and talking points for leads with no WhatsApp, email or LinkedIn path.",
  audit_status: "completed / failed / no_clear_opportunity (audited, but no meaningful problem was found).",
  processed_at: "UTC timestamp when this row finished processing.",
};

export interface ExportBusinessRow {
  raw: Record<string, unknown>;
  website_status: string;
  website_final: string;
  website_identity_confidence: number | null;
  website_source: string;
  score: number | null;
  opportunity_tier: string;
  lead_tier: string;
  best_channel: string;
  channel_reason: string;
  linkedin_url: string;
  linkedin_status: string;
  processed_at: string | null;
  audit?: {
    problems: { title: string }[];
    recommendations: { recommendation: string }[];
    priorities: { rank: number; title: string; category_label: string; severity: string; recommendation: string }[];
    report_r2_key: string;
    audit_status: string;
    audit_error: string;
  } | null;
  emails: { email: string; source_url: string; status: string }[];
}

function joinProblems(problems: { title: string }[]): string {
  return (problems || []).map((p, i) => `${i + 1}. ${p.title || ""}`).join(" | ");
}
function joinRecommendations(recs: { recommendation: string }[]): string {
  return (recs || []).map((r, i) => `${i + 1}. ${r.recommendation || ""}`).join(" | ");
}
function topIssueColumns(priorities: ExportBusinessRow["audit"] extends null ? never : any[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const c of TOP_ISSUE_COLUMNS) out[c] = "";
  for (const p of (priorities || []).slice(0, TOP_ISSUE_RANKS)) {
    const rank = p.rank;
    if (typeof rank !== "number" || rank < 1 || rank > TOP_ISSUE_RANKS) continue;
    out[`top_issue_${rank}`] = p.title || "";
    out[`top_issue_${rank}_category`] = p.category_label || "";
    out[`top_issue_${rank}_severity`] = (p.severity || "").toUpperCase();
    out[`top_issue_${rank}_fix`] = p.recommendation || "";
  }
  return out;
}

export function buildExportRows(originalColumns: string[], businesses: ExportBusinessRow[]): { headers: string[]; rows: Record<string, unknown>[] } {
  const collisions = new Set(ENRICHMENT_COLUMNS.filter((c) => originalColumns.includes(c)));
  const enrichNames = Object.fromEntries(ENRICHMENT_COLUMNS.map((c) => [c, collisions.has(c) ? `audit_${c}` : c]));
  const headers = [...originalColumns, ...ENRICHMENT_COLUMNS.map((c) => enrichNames[c])];

  const rows: Record<string, unknown>[] = businesses.map((b) => {
    const row: Record<string, unknown> = {};
    for (const col of originalColumns) row[col] = (b.raw || {})[col] ?? "";

    const e1 = b.emails[0];
    const e2 = b.emails[1];
    const values: Record<string, unknown> = {
      website_status: b.website_status || "",
      website_final: b.website_final || "",
      website_identity_confidence: b.website_identity_confidence === null || b.website_identity_confidence === undefined ? "" : Math.round(b.website_identity_confidence * 1000) / 1000,
      website_source: b.website_source || "",
      email_1: e1?.email || "", email_1_source: e1?.source_url || "", email_1_status: e1?.status || "",
      email_2: e2?.email || "", email_2_source: e2?.source_url || "", email_2_status: e2?.status || "",
      phone_raw_original: "", phone_normalized: "", phone_country: "", phone_type: "", phone_status: "unavailable",
      whatsapp_status: "no_phone", whatsapp_reason: "", whatsapp_url: "",
      linkedin_url: b.linkedin_url || "", linkedin_status: b.linkedin_status || "not_checked",
      website_score: b.score === null || b.score === undefined ? "" : b.score,
      opportunity_tier: b.opportunity_tier || "", lead_tier: b.lead_tier || "",
      problems: joinProblems(b.audit?.problems || []), recommendations: joinRecommendations(b.audit?.recommendations || []),
      ...topIssueColumns(b.audit?.priorities || []),
      contact_channel: CONTACT_CHANNEL_DISPLAY[b.best_channel || ""] ?? (b.best_channel || "SKIP").toUpperCase(),
      contact_channel_reason: b.channel_reason || "",
      whatsapp_message: "", whatsapp_draft_url: "", email_subject: "", email_message: "", email_draft_url: "",
      linkedin_message: "", call_notes: "",
      audit_report_path: b.audit?.report_r2_key || "",
      audit_status: b.audit?.audit_status || "not_processed",
      audit_error: b.audit?.audit_error || "",
      processed_at: b.processed_at || "",
    };

    for (const [canonical, outName] of Object.entries(enrichNames)) row[outName] = values[canonical] ?? "";
    return row;
  });

  return { headers, rows };
}

function cell(value: unknown): string | number {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return value;
  let s = String(value);
  if (["=", "+", "-", "@", "\t", "\r"].includes(s[0])) s = "'" + s;
  return s.slice(0, 32000);
}

export function exportCsv(headers: string[], rows: Record<string, unknown>[]): string {
  const escapeCsv = (v: string | number) => {
    const s = String(v);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [headers.map(escapeCsv).join(",")];
  for (const row of rows) lines.push(headers.map((h) => escapeCsv(cell(row[h]))).join(","));
  return "﻿" + lines.join("\r\n") + "\r\n";
}

export async function exportXlsx(headers: string[], rows: Record<string, unknown>[], originalColumnCount: number): Promise<ArrayBuffer> {
  const wb = new ExcelJS.Workbook();
  const ws = wb.addWorksheet("Leads");
  ws.addRow(headers);
  const headerRow = ws.getRow(1);
  headerRow.eachCell((c, colIdx) => {
    c.font = { color: { argb: "FFFFFFFF" }, bold: true, size: 10 };
    c.fill = { type: "pattern", pattern: "solid", fgColor: { argb: colIdx <= originalColumnCount ? "FF1E2537" : "FF3B5BDB" } };
    c.alignment = { vertical: "middle" };
  });

  for (const row of rows) ws.addRow(headers.map((h) => cell(row[h])));
  ws.views = [{ state: "frozen", ySplit: 1 }];

  headers.forEach((h, idx) => {
    const sample = rows.slice(0, 400).map((r) => String(cell(r[h])).slice(0, 80).length);
    const longest = Math.max(h.length, ...sample, 10);
    ws.getColumn(idx + 1).width = Math.min(52, Math.max(12, longest + 2));
  });

  const doc = wb.addWorksheet("Enrichment key");
  doc.addRow(["Column", "Meaning"]);
  doc.getRow(1).font = { bold: true };
  for (const [col, meaning] of Object.entries(COLUMN_DOCS)) {
    const r = doc.addRow([col, meaning]);
    r.getCell(2).alignment = { wrapText: true, vertical: "top" };
  }
  doc.getColumn(1).width = 32;
  doc.getColumn(2).width = 110;

  const buf = await wb.xlsx.writeBuffer();
  return buf as ArrayBuffer;
}

export function buildReportsZip(files: { name: string; content: string }[]): Uint8Array {
  const entries: Record<string, Uint8Array> = {};
  for (const f of files) entries[f.name] = strToU8(f.content);
  return zipSync(entries, { level: 6 });
}

function safeFilenamePart(name: string): string {
  return (name || "export").replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48) || "export";
}

export function exportFilename(jobId: number, jobName: string, ext: string): string {
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "").replace("T", "-");
  return `job${jobId}-${safeFilenamePart(jobName)}-${stamp}.${ext}`;
}
