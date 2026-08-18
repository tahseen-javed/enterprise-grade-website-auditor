// The long-running audit pipeline, as a Cloudflare Workflow. Replaces
// backend/app/core/pipeline.py's in-process asyncio worker pool: each
// audit (one business) is one durable Workflow instance, checkpointed at
// each step so a platform restart resumes rather than repeats work — the
// same guarantee the original got from per-lead stage checkpointing.
//
// Scope note: the original pipeline also runs a WhatsApp/email/LinkedIn
// outreach-drafting stage after scoring. That subsystem has no UI anywhere
// in this app (confirmed by reading the frontend — the lead drawer only has
// Overview/Scorecard/Problems/Evidence tabs, never a drafts view) and was
// intentionally left out of this port; see cloudflare/README.md. Everything
// a user can actually see or click is preserved.
import { WorkflowEntrypoint, WorkflowEvent, WorkflowStep } from "cloudflare:workers";
import type { AuditWorkflowParams, Env, Finding } from "../types";
import { Fetcher } from "../core/fetcher";
import { SubrequestBudget } from "../core/limits";
import { verifyDirectWebsite, hasWebsite, STATUS_NOT_A_WEBSITE, STATUS_NO_WEBSITE, DiscoveryResult } from "../core/discovery";
import { crawlSite } from "../core/crawler";
import { extractContacts, ExtractionResult, FoundEmail } from "../core/extract";
import { validateAll, EmailValidation } from "../core/emailValidate";
import * as ps from "../core/pagespeed";
import { runAllChecks, runExtraChecks, noWebsiteFindings } from "../core/auditChecks";
import {
  auditCategoryOf, buildExecutiveSummary, buildScorecard, buildRecommendations, computeScore, hasClearOpportunity,
  leadTier, selectProblems, tierForScore, topPriorities,
} from "../core/scoring";
import { renderReport } from "../core/reportHtml";
import { getEngine, getWeights } from "../lib/settings";
import { putReport, reportKey } from "../lib/r2";
import * as q from "../db/queries";

// Cloudflare-specific safety ceilings, applied on top of whatever the user
// configured in Settings, so a single audit can never come close to the
// Workflow instance's subrequest budget (50 external/instance on the
// Workers Free plan — see core/limits.ts).
const MAX_PAGES_CEILING = 10;
const MAX_LINK_CHECKS_CEILING = 5;
const MAX_RETRIES_CEILING = 1;
const MAX_EMAILS_VALIDATED = 5;
const SUBREQUEST_BUDGET_TOTAL = 40;

// Cloudflare Workflows caps a single step's checkpointed output at 1MiB.
// Observed in production against real, content-heavy sites (a major news
// homepage, a marketing site) that the crawl-and-audit step's own JSON
// output can approach that even *after* excluding raw page HTML — findings'
// `evidence` objects (built from page text/link samples) are the next most
// likely source on an unusually content-rich site. Rather than let a
// pathological site fail the whole audit outright, progressively shed the
// least-important detail — evidence first, then excess low-priority
// findings — until the output safely fits, in three escalating tiers. Tier
// 0 (the overwhelming majority of sites) passes through unchanged.
const STEP_OUTPUT_SAFE_BYTES = 900_000; // ~900KB, comfortable margin under the 1MiB hard cap

function shrinkToFit<T extends { findings: Finding[]; extraFindings: Finding[]; pagesSummary: PageSummary[] }>(out: T): T {
  const size = () => JSON.stringify(out).length;
  if (size() <= STEP_OUTPUT_SAFE_BYTES) return out;

  // Tier 1: evidence is the richest (and least essential — title/detail
  // already state the finding in words) field on a Finding; blank it first.
  const stripEvidence = (f: Finding): Finding => ({ ...f, evidence: {} });
  out.findings = out.findings.map(stripEvidence);
  out.extraFindings = out.extraFindings.map(stripEvidence);
  if (size() <= STEP_OUTPUT_SAFE_BYTES) return out;

  // Tier 2: keep only the highest-impact findings per list (scoring and the
  // report both already rank by severity/deduction, so this trims the least
  // consequential entries first, not arbitrarily).
  const byImpact = (a: Finding, b: Finding) => b.deduction - a.deduction;
  out.findings = [...out.findings].sort(byImpact).slice(0, 40);
  out.extraFindings = [...out.extraFindings].sort(byImpact).slice(0, 40);
  if (size() <= STEP_OUTPUT_SAFE_BYTES) return out;

  // Tier 3: last resort — cap the crawled-pages list shown in the report's
  // appendix. Scoring/report logic all treat a shorter pagesSummary safely.
  out.pagesSummary = out.pagesSummary.slice(0, 5);
  return out;
}

async function activity(db: D1Database, jobId: number, businessId: number | null, businessName: string, message: string, opts: { stage?: string; level?: string } = {}) {
  try {
    await q.addEvent(db, { jobId, businessId, businessName, message, stage: opts.stage || "", level: opts.level || "info" });
  } catch {
    /* the activity log must never break the pipeline */
  }
}

interface PageSummary { type: string; url: string; status: number | null; words: number; elapsed_ms: number }

// Everything the rest of the workflow needs after crawling+auditing a site —
// deliberately excludes the full crawled page content (raw HTML, full link
// lists, full text). Cloudflare Workflows caps a single step's checkpointed
// output at 1MiB; a real, content-heavy homepage's raw HTML alone can
// exceed that (observed in production against a major news homepage), so
// the heavy `CrawlResult` from crawlSite() must stay a local variable inside
// one step's closure and never be returned as a step's own output — only
// this already-reduced summary crosses the step boundary.
interface AuditOutcome {
  crawlOk: boolean;
  homeStatus: number | null;
  isHttps: boolean | null;
  redirectChain: string[];
  homeResponseMs: number | null;
  pagesCrawled: number;
  pagesSummary: PageSummary[];
  crawlErrorMessage: string;
  facts: Record<string, any>;
  findings: Finding[];
  extraFacts: Record<string, any>;
  extraFindings: Finding[];
  extracted: ExtractionResult;
  validations: EmailValidation[];
}

export class AuditWorkflow extends WorkflowEntrypoint<Env, AuditWorkflowParams> {
  async run(event: WorkflowEvent<AuditWorkflowParams>, step: WorkflowStep) {
    const { jobId, businessId } = event.payload;
    const db = this.env.DB;
    const budget = new SubrequestBudget(SUBREQUEST_BUDGET_TOTAL);

    try {
      const ctx = await step.do("load-context", async () => {
        const job = await q.getJob(db, jobId);
        const business = await q.getBusiness(db, businessId);
        if (!job || !business) throw new Error(`Job ${jobId} or business ${businessId} does not exist.`);
        const engine = await getEngine(db);
        const weights = await getWeights(db);
        return { job, business, engine, weights };
      });

      await step.do("mark-running", async () => {
        await q.setJobStatus(db, jobId, "running", { startedAt: true });
        await q.startJobItem(db, businessId);
        await activity(db, jobId, businessId, ctx.business.name, "Processing started", { stage: "start" });
      });

      // ---------------- discovery ----------------
      const disc = await step.do(
        "discovery",
        // No step-level retries here: on a slow/blocking site, each retry of
        // this step re-runs the whole callback including its budget.take()
        // guard, and step retries stacked with the platform's own instance
        // replay semantics were observed in production to burn through the
        // entire subrequest budget before a single crawl request ever went
        // out — turning "be resilient" into "guarantee failure". A single
        // attempt, with the user's own "Retry failed" button as the manual
        // fallback, is safer under the Free plan's tight budget. Fetcher's
        // own request-level retry (maxRetries in engine settings) still
        // applies underneath this for ordinary transient HTTP failures.
        { retries: { limit: 0, delay: "1 second" }, timeout: "45 seconds" },
        async (): Promise<DiscoveryResult> => {
          const fetcher = new Fetcher({
            userAgent: ctx.engine.user_agent, timeoutS: ctx.engine.request_timeout_s,
            perDomainDelayMs: ctx.engine.per_domain_delay_ms, maxBytes: ctx.engine.max_page_bytes,
            maxRetries: Math.min(ctx.engine.max_retries, MAX_RETRIES_CEILING), respectRobots: ctx.engine.respect_robots,
          });
          if (!budget.take()) return { website_original: ctx.business.website_original, website_final: "", status: STATUS_NO_WEBSITE, source: "", identity_confidence: null, identity_verdict: "", identity_signals: [], notes: ["Subrequest budget exhausted before discovery could run."], error_code: "budget_exhausted", error_message: "", redirect_chain: [], http_status: null, response_ms: null, candidates_tried: [], social_profile_url: "" };
          return verifyDirectWebsite(fetcher, ctx.business.website_original);
        },
      );

      if (!hasWebsite(disc)) {
        await step.do("skip-no-website", async () => {
          await q.skipNoWebsite(db, businessId, {
            website_original: disc.website_original, website_final: disc.website_final, status: disc.status,
            identity_confidence: disc.identity_confidence, source: disc.source,
          });
          if (disc.error_code) await q.recordError(db, { jobId, businessId, stage: "discovery", code: disc.error_code, message: disc.error_message, retryable: ["timeout", "connection_error"].includes(disc.error_code) });
          await activity(db, jobId, businessId, ctx.business.name, `No usable website (${disc.status})`, { stage: "discovery", level: "warn" });
        });
        await this.finishJob(db, jobId, "completed");
        return;
      }

      await activity(db, jobId, businessId, ctx.business.name, `Website confirmed: ${disc.website_final}`, { stage: "discovery" });

      // ---------------- crawl + extract + validate + audit (one step) ----------------
      // Deliberately one step, not four: the intermediate CrawlResult (with
      // raw HTML) must never be a step's *return value* (see AuditOutcome's
      // comment above), so everything that needs it runs inside this single
      // closure, and only the reduced AuditOutcome crosses the checkpoint
      // boundary.
      const outcome: AuditOutcome = await step.do(
        "crawl-and-audit",
        { retries: { limit: 0, delay: "1 second" }, timeout: "100 seconds" },
        async (): Promise<AuditOutcome> => {
          const fetcher = new Fetcher({
            userAgent: ctx.engine.user_agent, timeoutS: ctx.engine.request_timeout_s,
            perDomainDelayMs: ctx.engine.per_domain_delay_ms, maxBytes: ctx.engine.max_page_bytes,
            maxRetries: Math.min(ctx.engine.max_retries, MAX_RETRIES_CEILING), respectRobots: ctx.engine.respect_robots,
          });
          const crawl = await crawlSite(fetcher, disc.website_final, {
            maxPages: Math.min(ctx.engine.max_pages_per_site, MAX_PAGES_CEILING),
            maxDepth: ctx.engine.max_crawl_depth, totalBudgetS: Math.min(ctx.engine.total_site_budget_s, 80),
            maxLinkChecks: MAX_LINK_CHECKS_CEILING, budget,
          });

          const pagesSummary: PageSummary[] = crawl.pages.map((p) => ({
            type: p.page_type, url: p.final_url || p.url, status: p.status, words: p.word_count, elapsed_ms: p.elapsed_ms,
          }));

          if (!crawl.ok) {
            return {
              crawlOk: false, homeStatus: crawl.home_status, isHttps: crawl.is_https, redirectChain: crawl.redirect_chain,
              homeResponseMs: crawl.home_response_ms, pagesCrawled: 0, pagesSummary: [],
              crawlErrorMessage: crawl.errors[0]?.message ?? "",
              facts: {}, findings: [], extraFacts: {}, extraFindings: [],
              extracted: { emails: [], whatsapp_links: [], whatsapp_numbers: [], social_links: [], linkedin_urls: [], contact_form_urls: [], contact_names: [] },
              validations: [],
            };
          }

          let extracted: ExtractionResult;
          try {
            extracted = extractContacts(crawl, disc.website_final ? new URL(disc.website_final).hostname : "");
          } catch {
            extracted = { emails: [], whatsapp_links: [], whatsapp_numbers: [], social_links: [], linkedin_urls: [], contact_form_urls: [], contact_names: [] };
          }

          let validations: EmailValidation[] = [];
          try {
            validations = await validateAll(extracted.emails, { enableMx: ctx.engine.enable_mx_lookup, dnsTimeoutS: ctx.engine.dns_timeout_s, limit: MAX_EMAILS_VALIDATED, budget });
          } catch {
            validations = [];
          }

          let perf: ps.PageSpeedResult | null = null;
          if (ctx.engine.pagespeed_enabled && ctx.engine.pagespeed_api_key && budget.take()) {
            try {
              perf = await ps.measure(crawl.final_url, ctx.engine.pagespeed_api_key, ctx.engine.pagespeed_strategy, 55);
            } catch (exc: any) {
              await q.recordError(db, { jobId, businessId, stage: "audit", code: "pagespeed_error", message: String(exc?.message || exc), retryable: true });
            }
          }

          const [facts, findings] = runAllChecks(crawl, { extracted, perf });
          const [extraFacts, extraFindings] = runExtraChecks(crawl);

          const out = {
            crawlOk: true, homeStatus: crawl.home_status, isHttps: crawl.is_https, redirectChain: crawl.redirect_chain,
            homeResponseMs: crawl.home_response_ms, pagesCrawled: crawl.pages.length, pagesSummary, crawlErrorMessage: "",
            facts, findings, extraFacts, extraFindings, extracted, validations,
          };
          return shrinkToFit(out);
        },
      );

      let auditKind = "website";
      let auditStatus = "completed";
      let auditError = "";
      let findings: Finding[] = outcome.findings;
      let extraFindings: Finding[] = outcome.extraFindings;

      if (outcome.crawlOk) {
        await activity(db, jobId, businessId, ctx.business.name, `Crawled ${outcome.pagesCrawled} page(s)`, { stage: "crawl" });
        await activity(db, jobId, businessId, ctx.business.name, `Audit complete: ${findings.length + extraFindings.length} finding(s)`, { stage: "audit" });
      } else if (disc.status === STATUS_NOT_A_WEBSITE) {
        auditKind = "no_website";
        findings = noWebsiteFindings("The listed web address is a third-party profile, not a website the business owns.", disc.social_profile_url);
      } else {
        auditStatus = "failed";
        auditError = disc.error_message || outcome.crawlErrorMessage || `The website could not be audited (status: ${disc.status}).`;
        await activity(db, jobId, businessId, ctx.business.name, `Audit could not be completed: ${auditError}`, { stage: "audit", level: "error" });
      }

      // ---------------- score + scorecard + report ----------------
      const scored = await step.do("score-and-report", { timeout: "20 seconds" }, async () => {
        let scoreResult = null;
        let problems: any[] = [];
        let recommendations: any[] = [];
        let oppTier = "";
        let scoreVal: number | null = null;
        let scorecard: any = {};
        let priorities: any[] = [];
        let executiveSummary: any = {};

        if (auditStatus === "completed" && auditKind === "website") {
          scoreResult = computeScore(findings, ctx.weights.weights);
          scoreVal = scoreResult.score;
          [oppTier] = tierForScore(scoreVal, ctx.weights.tiers);
          problems = selectProblems(findings, ctx.weights.max_problems);
          recommendations = buildRecommendations(problems, findings);

          const allPremium = [...findings, ...extraFindings];
          const localSeoApplicable = outcome.extraFacts.local_seo?.applicable ?? true;
          scorecard = buildScorecard(allPremium, undefined, {
            categoryApplicability: { local_seo: localSeoApplicable },
            applicabilityReason: { local_seo: outcome.extraFacts.local_seo?.reason || "" },
            pagespeedMeasured: Boolean(outcome.facts.pagespeed?.measured),
          });
          priorities = topPriorities(allPremium);
          executiveSummary = buildExecutiveSummary(scorecard, allPremium, priorities);
        } else if (auditKind === "no_website") {
          problems = findings.map((fnd, i) => ({
            rank: i + 1, code: fnd.code, category: fnd.display_category, category_label: fnd.display_category,
            severity: fnd.severity, title: fnd.title, detail: fnd.detail, evidence: fnd.evidence,
            impact_points: 0, is_strong_signal: true,
          }));
          recommendations = findings.filter((fd) => fd.recommendation).map((fd, i) => ({ rank: i + 1, problem_code: fd.code, problem: fd.title, recommendation: fd.recommendation, category: fd.display_category, severity: fd.severity }));
          oppTier = "No website";
        }

        const [clear, noOppReason] = hasClearOpportunity(problems, auditKind === "website" ? scoreVal : 50, ctx.weights.min_problems_for_outreach);

        let reportKeyStr = "";
        if (auditStatus === "completed" || auditKind === "no_website") {
          const location = [ctx.business.city, ctx.business.state, ctx.business.country].filter(Boolean).join(", ");
          const contacts: any[] = [];
          for (const v of outcome.validations.slice(0, 3)) contacts.push({ label: "Email", value: v.email, status: v.status, pill: ["valid_public", "mx_valid"].includes(v.status) ? "ok" : "warn" });
          if (!outcome.validations.length) contacts.push({ label: "Email", value: "None published on the website", status: "", pill: "neutral" });
          for (const u of outcome.extracted.contact_form_urls.slice(0, 1)) contacts.push({ label: "Contact form", value: u, status: "found", pill: "ok" });

          const pages = outcome.pagesSummary.map((p) => ({ type: p.type, url: p.url, status: p.status ?? "—" }));

          const html = renderReport({
            business: { name: ctx.business.name, location, category: ctx.business.category },
            audit: {
              website: disc.website_final || disc.website_original, score: scoreVal,
              opportunity_tier: scoreResult ? tierForScore(scoreResult.score, ctx.weights.tiers)[0] : "",
              technical: outcome.facts.technical || {}, mobile: outcome.facts.mobile || {}, conversion: outcome.facts.conversion || {},
              audit_error: auditError,
            } as any,
            problems, recommendations, contacts, pages, generator: "",
            scorecard: Object.keys(scorecard).length ? scorecard : undefined,
            legacyFindings: findings, extraFindings, extraFacts: outcome.extraFacts, priorities, executiveSummary,
          });

          const candidateKey = reportKey(jobId, businessId, ctx.business.name);
          try {
            if (!this.env.REPORTS) throw new Error("R2 REPORTS binding is not configured.");
            await putReport(this.env.REPORTS, candidateKey, html);
            reportKeyStr = candidateKey;
            await activity(db, jobId, businessId, ctx.business.name, "Audit report generated", { stage: "report" });
          } catch (exc: any) {
            // The score/scorecard is still fully computed and persisted below;
            // only the downloadable HTML report is affected. Recorded as a
            // retryable error rather than failing the whole audit, since a
            // storage outage is exactly the kind of thing that resolves on
            // its own and shouldn't corrupt an otherwise-successful audit.
            await q.recordError(db, { jobId, businessId, stage: "report", code: "report_storage_unavailable", message: String(exc?.message || exc), retryable: true });
            await activity(db, jobId, businessId, ctx.business.name, `Report could not be saved (storage unavailable): ${String(exc?.message || exc)}`, { stage: "report", level: "warn" });
          }
        }

        return { scoreResult, problems, recommendations, oppTier, scoreVal, scorecard, priorities, executiveSummary, clear, noOppReason, reportKey: reportKeyStr };
      });

      // ---------------- persist ----------------
      await step.do("persist", { timeout: "15 seconds" }, async () => {
        const tier = leadTier({
          score: auditKind === "website" ? scored.scoreVal : auditKind === "no_website" ? 50 : null,
          websiteStatus: disc.status, hasUsableContact: false,
          strongProblemCount: scored.problems.filter((p: any) => p.is_strong_signal).length,
          problemCount: scored.problems.length, auditKind,
          reviewCount: ctx.business.review_count, rating: ctx.business.rating,
        });

        await q.persistAuditResult(db, {
          businessId,
          website: disc.website_final || disc.website_original, auditKind,
          httpStatus: outcome.crawlOk ? outcome.homeStatus : disc.http_status,
          isHttps: outcome.crawlOk ? outcome.isHttps : null,
          redirectChain: outcome.crawlOk ? outcome.redirectChain : disc.redirect_chain,
          responseMs: outcome.crawlOk ? outcome.homeResponseMs : disc.response_ms,
          pagesCrawled: outcome.pagesCrawled,
          pages: outcome.pagesSummary,
          technical: outcome.facts.technical || {}, conversion: outcome.facts.conversion || {}, mobile: outcome.facts.mobile || {},
          performance: (outcome.facts.technical || {}).pagespeed || {}, trust: outcome.facts.trust || {}, content: outcome.facts.content || {},
          subscores: scored.scoreResult?.subscores || {}, score: scored.scoreVal, opportunityTier: scored.oppTier,
          scoreExplanation: scored.scoreResult?.explanation || [],
          problems: scored.problems, recommendations: scored.recommendations,
          extra: {
            facts: outcome.extraFacts,
            findings: extraFindings.map((fd) => ({ ...fd, premium_category: auditCategoryOf(fd) })),
            legacy_findings: findings.map((fd) => ({ ...fd, premium_category: auditCategoryOf(fd) })),
            scorecard: scored.scorecard, priorities: scored.priorities, executive_summary: scored.executiveSummary,
          },
          reportR2Key: scored.reportKey, auditStatus: scored.clear ? auditStatus : (auditStatus !== "completed" ? auditStatus : "no_clear_opportunity"),
          auditError: auditError || (scored.clear ? "" : scored.noOppReason),
          websiteFinal: disc.website_final, websiteStatus: disc.status,
          websiteIdentityConfidence: disc.identity_confidence, websiteSource: disc.source,
          leadTier: tier.tier, bestChannel: "none", channelReason: "Outreach routing is not part of this deployment.",
          linkedinUrl: outcome.extracted.linkedin_urls[0] || "", linkedinStatus: outcome.extracted.linkedin_urls.length ? "found" : "not_checked",
          emails: outcome.validations.map((v, i) => {
            const found = outcome.extracted.emails.find((e: FoundEmail) => e.email === v.email);
            return {
              email: v.email, sourceUrl: found?.source_url || "", sourceType: found?.source_type || "", pageType: found?.page_type || "",
              status: v.status, confidence: v.confidence, isRole: v.is_role, isDisposable: v.is_disposable,
              domainMatchesSite: v.domain_matches_site, mxRecords: v.mx_records, notes: v.notes,
            };
          }),
        });

        await q.completeJobItem(db, businessId);
        await activity(db, jobId, businessId, ctx.business.name, `Complete — lead tier ${tier.tier}`, { stage: "done" });
      });

      await this.finishJob(db, jobId, "completed");
    } catch (exc: any) {
      const message = `${exc?.name || "Error"}: ${exc?.message || exc}`;
      try {
        // A platform-level interruption (e.g. "Durable Object reset because
        // its code was updated", observed in production when a deploy lands
        // mid-run) can throw *after* persistAuditResult already wrote a real,
        // complete audit — the work genuinely succeeded even though this
        // invocation didn't reach its own finish line. Blindly marking the
        // item/job "failed" here would bury a correct result under a
        // misleading status, so check for that already-persisted result
        // first and treat it as success (with the interruption logged, not
        // hidden) rather than as a failure.
        const already = await db.prepare(`SELECT id FROM website_audits WHERE business_id = ?`).bind(businessId).first<{ id: number }>();
        if (already) {
          await q.recordError(db, { jobId, businessId, stage: "workflow", code: "interrupted_after_success", message, retryable: false });
          await q.completeJobItem(db, businessId);
          await this.finishJob(db, jobId, "completed");
          return;
        }
        await q.recordError(db, { jobId, businessId, stage: "workflow", code: "unhandled", message, retryable: false });
        await q.failJobItem(db, businessId, "workflow", message, false);
      } catch {
        /* best effort */
      }
      await this.finishJob(db, jobId, "failed", message);
    }
  }

  private async finishJob(db: D1Database, jobId: number, status: "completed" | "failed" | "cancelled", lastError?: string) {
    await q.setJobStatus(db, jobId, status, { finishedAt: true, lastError });
    await q.addEvent(db, { jobId, message: `Job ${status}`, stage: "job", level: status === "completed" ? "info" : "warn" });
  }
}
