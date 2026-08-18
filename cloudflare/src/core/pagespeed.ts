// Optional Google PageSpeed Insights integration. Ported from
// backend/app/core/pagespeed.py. Off unless the user supplies their own key
// in Settings.
const ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed";

export interface PageSpeedResult {
  measured: boolean;
  strategy: string;
  url: string;
  source: string;
  error?: string;
  error_message?: string;
  performance_score?: number;
  fetched_url?: string;
  lcp_s?: number | null;
  fcp_s?: number | null;
  tbt_ms?: number | null;
  cls?: number | null;
  speed_index_s?: number | null;
  opportunities?: { id: string; title: string; savings_ms: number }[];
  field_data_category?: string;
}

export async function measure(url: string, apiKey: string, strategy: "mobile" | "desktop" = "mobile", timeoutS = 55): Promise<PageSpeedResult> {
  const out: PageSpeedResult = { measured: false, strategy, url, source: "Google PageSpeed Insights API" };
  if (!apiKey) {
    out.error = "not_configured";
    out.error_message = "No PageSpeed API key is configured.";
    return out;
  }

  const params = new URLSearchParams({ url, key: apiKey, strategy, category: "performance" });
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutS * 1000);
  let resp: Response;
  try {
    resp = await fetch(`${ENDPOINT}?${params.toString()}`, { signal: controller.signal });
  } catch (exc: any) {
    out.error = exc?.name === "AbortError" ? "timeout" : "http_error";
    out.error_message = exc?.name === "AbortError" ? `PageSpeed did not respond within ${timeoutS}s.` : `PageSpeed request failed: ${exc?.message || exc}`;
    return out;
  } finally {
    clearTimeout(timer);
  }

  if (resp.status !== 200) {
    out.error = `http_${resp.status}`;
    let detail = "";
    try {
      detail = ((await resp.json()) as any)?.error?.message || "";
    } catch {
      detail = (await resp.text()).slice(0, 300);
    }
    out.error_message = `PageSpeed returned HTTP ${resp.status}: ${detail}`;
    return out;
  }

  let data: any;
  try {
    data = await resp.json();
  } catch (exc: any) {
    out.error = "parse_error";
    out.error_message = `Could not parse the PageSpeed response: ${exc?.message || exc}`;
    return out;
  }

  const lighthouse = data.lighthouseResult || {};
  const categories = lighthouse.categories || {};
  const audits = lighthouse.audits || {};
  const perf = categories.performance?.score;
  if (perf === undefined || perf === null) {
    out.error = "no_score";
    out.error_message = "PageSpeed returned no performance score for this URL.";
    return out;
  }

  out.measured = true;
  out.performance_score = Math.round(perf * 100);
  out.fetched_url = lighthouse.finalUrl || url;

  const num = (key: string): number | null => {
    const v = audits[key]?.numericValue;
    return typeof v === "number" ? Math.round(v * 1000) / 1000 : null;
  };
  const lcp = num("largest-contentful-paint");
  const fcp = num("first-contentful-paint");
  const tbt = num("total-blocking-time");
  const cls = num("cumulative-layout-shift");
  const si = num("speed-index");

  out.lcp_s = lcp !== null ? Math.round((lcp / 1000) * 100) / 100 : null;
  out.fcp_s = fcp !== null ? Math.round((fcp / 1000) * 100) / 100 : null;
  out.tbt_ms = tbt !== null ? Math.round(tbt) : null;
  out.cls = cls !== null ? Math.round(cls * 1000) / 1000 : null;
  out.speed_index_s = si !== null ? Math.round((si / 1000) * 100) / 100 : null;

  const opportunities: { id: string; title: string; savings_ms: number }[] = [];
  for (const [key, audit] of Object.entries<any>(audits)) {
    const details = audit.details || {};
    if (details.type !== "opportunity") continue;
    const savings = details.overallSavingsMs;
    if (typeof savings === "number" && savings >= 250) {
      opportunities.push({ id: key, title: audit.title || "", savings_ms: Math.round(savings) });
    }
  }
  opportunities.sort((a, b) => b.savings_ms - a.savings_ms);
  out.opportunities = opportunities.slice(0, 6);

  const loading = data.loadingExperience || {};
  if (loading.overall_category) out.field_data_category = loading.overall_category;

  return out;
}

export async function checkAvailability(apiKey: string): Promise<{ status: string; detail: string }> {
  if (!apiKey) return { status: "disabled", detail: "No API key configured (optional integration)." };
  const result = await measure("https://example.com", apiKey, "mobile", 30);
  if (result.measured) return { status: "healthy", detail: "PageSpeed API responded successfully." };
  return { status: "error", detail: result.error_message || "PageSpeed API did not return a score." };
}
