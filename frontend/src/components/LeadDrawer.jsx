import { useState } from 'react'
import { api, downloadUrl } from '../lib/api'
import {
  AUDIT_STATUS, CHECK_STATUS, WEBSITE_STATUS, dateTime, describe, tierClass,
} from '../lib/format'
import { useFetch } from '../lib/store'
import { BandPill, CategoryScorecards, ScoreDial, SeverityBreakdown } from './charts'
import { IconAlert, IconCheck, IconExternal, IconSparkle } from './icons'
import { Alert, Badge, CopyButton, Drawer, Empty, ErrorState, KV, Progress, Skeleton } from './ui'

const SEVERITY_LABEL = { high: 'Critical', medium: 'High priority', low: 'Warning' }
const SEVERITY_RANK = { high: 0, medium: 1, low: 2 }
const SEVERITY_TONE = (sev) => (sev === 'high' ? 'danger' : sev === 'medium' ? 'warn' : 'ok')

export default function LeadDrawer({ leadId, onClose }) {
  const [tab, setTab] = useState('overview')
  const { data, loading, error, reload } = useFetch(() => api.lead(leadId), [leadId], {
    skip: !leadId,
  })

  const head = data ? (
    <>
      <div className="row" style={{ gap: 8, marginBottom: 3 }}>
        {data.lead_tier && <span className={`tier ${tierClass(data.lead_tier)}`}>{data.lead_tier}</span>}
        <h2 className="break" style={{ minWidth: 0 }}>{data.name}</h2>
      </div>
      <div className="row row-wrap small muted" style={{ gap: 8 }}>
        {data.category && <span>{data.category}</span>}
        {(data.city || data.country) && <span>· {[data.city, data.state, data.country].filter(Boolean).join(', ')}</span>}
        {data.rating != null && <span>· ★ {data.rating} ({data.review_count ?? 0})</span>}
      </div>
    </>
  ) : (
    <h2>Lead</h2>
  )

  return (
    <Drawer open={!!leadId} onClose={onClose} head={head}>
      {loading && <Skeleton rows={7} />}
      {error && <ErrorState error={error} onRetry={reload} />}
      {data && (
        <div className="stack">
          <div className="seg" style={{ alignSelf: 'flex-start', flexWrap: 'wrap' }}>
            {[
              ['overview', 'Overview'],
              ['scorecard', 'Audit report'],
              ['problems', `Problems (${data.problem_count})`],
              ['evidence', 'Evidence'],
            ].map(([id, label]) => (
              <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
                {label}
              </button>
            ))}
          </div>

          {tab === 'overview' && <Overview data={data} />}
          {tab === 'scorecard' && <ScorecardTab data={data} />}
          {tab === 'problems' && <Problems data={data} />}
          {tab === 'evidence' && <Evidence data={data} />}
        </div>
      )}
    </Drawer>
  )
}

/* ------------------------------------------------------------------ */

function Overview({ data }) {
  const site = describe(WEBSITE_STATUS, data.website_status)

  return (
    <>
      <div className="card card-pad">
        <div className="row" style={{ gap: 'var(--sp-5)', alignItems: 'center', flexWrap: 'wrap' }}>
          <ScoreDial score={data.score} size={112} />
          <div style={{ flex: 1, minWidth: 210 }}>
            <div className="row row-wrap" style={{ gap: 7, marginBottom: 10 }}>
              <Badge tone={site.tone}>{site.label}</Badge>
              {data.opportunity_tier && <Badge tone="brand">{data.opportunity_tier} opportunity</Badge>}
              {data.audit_status && (
                <Badge tone={describe(AUDIT_STATUS, data.audit_status).tone}>
                  {describe(AUDIT_STATUS, data.audit_status).label}
                </Badge>
              )}
            </div>
            {data.audit?.score_explanation?.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                {data.audit.score_explanation.map((row) => (
                  <div key={row.category} className="meter-row">
                    <span className="name">{row.label}</span>
                    <Progress value={row.opportunity} />
                    <span className="val">{row.opportunity}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="small muted">
                {data.audit?.audit_error || 'This lead has no website score.'}
              </p>
            )}
          </div>
        </div>
        {data.audit?.score_explanation?.length > 0 && (
          <p className="xsmall muted" style={{ marginTop: 14 }}>
            Higher means more room to improve. Each bar is 100 minus the health points removed by the
            checks that actually failed, weighted by your Settings.
          </p>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Website</h2>
          <div className="spacer" />
          {data.has_report && (
            <a className="btn btn-sm" href={downloadUrl.report(data.id)} target="_blank" rel="noreferrer">
              <IconExternal size={12} /> Audit report
            </a>
          )}
        </div>
        <div className="card-body">
          <KV
            items={[
              {
                k: 'Final URL',
                v: data.website_final ? (
                  <a href={data.website_final} target="_blank" rel="noreferrer" className="break">
                    {data.website_final}
                  </a>
                ) : (
                  <span className="muted">None</span>
                ),
              },
              data.website_original && { k: 'From your CSV', v: <span className="break mono xsmall">{data.website_original}</span> },
              { k: 'Source', v: data.website_source || '—' },
              {
                k: 'Identity confidence',
                v:
                  data.website_identity_confidence != null
                    ? `${Math.round(data.website_identity_confidence * 100)}%`
                    : '—',
              },
              { k: 'HTTP status', v: data.audit?.http_status ?? '—' },
              { k: 'Response time', v: data.audit?.response_ms != null ? `${data.audit.response_ms} ms` : '—' },
              { k: 'Pages crawled', v: data.audit?.pages_crawled ?? 0 },
              { k: 'Processed', v: dateTime(data.processed_at) },
            ]}
          />
        </div>
      </div>

      {data.errors?.length > 0 && (
        <div className="card">
          <div className="card-head"><h2>Errors recorded</h2></div>
          <div className="card-body stack" style={{ gap: 8 }}>
            {data.errors.map((e, i) => (
              <div key={i} className="row" style={{ gap: 8, alignItems: 'flex-start' }}>
                <IconAlert size={14} style={{ color: 'var(--danger)', marginTop: 2, flex: '0 0 auto' }} />
                <div style={{ minWidth: 0 }}>
                  <div className="small strong">
                    {e.stage} · {e.code}{' '}
                    <Badge tone={e.retryable ? 'warn' : 'neutral'}>
                      {e.retryable ? 'retryable' : 'not retryable'}
                    </Badge>
                  </div>
                  <div className="xsmall muted break">{e.message}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  )
}

/* ------------------------------------------------------------------ */

function ScorecardTab({ data }) {
  const [activeCategory, setActiveCategory] = useState(null)
  const extra = data.audit?.extra || {}
  const sc = extra.scorecard || {}
  const priorities = extra.priorities || []
  const summary = extra.executive_summary || {}
  const checks = sc.checks || {
    passed: [], warnings: [], failed: [], not_verified: [], not_applicable: [],
    passed_count: 0, warning_count: 0, failed_count: 0, not_verified_count: 0,
    not_applicable_count: 0, total_checked: 0,
  }

  if (!sc.categories?.length) {
    return (
      <Empty title="No premium scorecard for this lead">
        {data.audit?.audit_error ||
          'This audit ran before the premium scorecard existed, or the site could not be crawled.'}
      </Empty>
    )
  }

  // Every finding that feeds the scorecard - legacy-category findings (e.g.
  // no_https) carry a server-computed `premium_category` alongside their own
  // `category`, so this groups exactly the way the full HTML report does,
  // not just the newer premium-only checks.
  const allFindings = [...(extra.legacy_findings || []), ...(extra.findings || [])]
  const byCategory = {}
  for (const f of allFindings) {
    if (f.deduction <= 0) continue
    const cat = f.premium_category || f.category
    ;(byCategory[cat] ||= []).push(f)
  }
  for (const items of Object.values(byCategory)) {
    items.sort((a, b) => (SEVERITY_RANK[a.severity] ?? 3) - (SEVERITY_RANK[b.severity] ?? 3) || b.deduction - a.deduction)
  }

  const visibleCategories = activeCategory
    ? sc.categories.filter((c) => c.category === activeCategory)
    : sc.categories

  return (
    <div className="stack">
      <div className="card card-pad">
        <div className="row" style={{ gap: 'var(--sp-5)', alignItems: 'center', flexWrap: 'wrap' }}>
          <ScoreDial score={sc.overall_score} size={112} label="health" />
          <div style={{ flex: 1, minWidth: 220 }}>
            <div className="row row-wrap" style={{ gap: 7, marginBottom: 10 }}>
              <BandPill score={sc.overall_score} />
              <Badge tone="neutral">{checks.passed_count}/{checks.total_checked} checks passed</Badge>
              {checks.failed_count > 0 && <Badge tone="danger">{checks.failed_count} critical</Badge>}
              {checks.warning_count > 0 && <Badge tone="warn">{checks.warning_count} warnings</Badge>}
            </div>
            <p className="small" style={{ margin: 0, color: 'var(--ink-2)' }}>
              {summary.headline || 'This is a health score — higher is better, unlike the opportunity score on Overview.'}
            </p>
          </div>
        </div>
      </div>

      {data.has_report && (
        <a className="btn btn-block btn-primary" href={downloadUrl.report(data.id)} target="_blank" rel="noreferrer">
          <IconExternal size={13} /> Open the full premium report
        </a>
      )}

      <div className="grid grid-2">
        <div className="card">
          <div className="card-head"><h2>What's working well</h2></div>
          <div className="card-body">
            {summary.whats_working?.length ? (
              <ul className="small" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9, color: 'var(--ink-2)' }}>
                {summary.whats_working.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            ) : (
              <p className="small muted" style={{ margin: 0 }}>No category currently scores in the "Good" range.</p>
            )}
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h2>Biggest opportunities</h2></div>
          <div className="card-body">
            {summary.biggest_opportunities?.length ? (
              <ul className="small" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9, color: 'var(--ink-2)' }}>
                {summary.biggest_opportunities.map((o, i) => <li key={i}>{o}</li>)}
              </ul>
            ) : (
              <p className="small muted" style={{ margin: 0 }}>No category currently scores below 70.</p>
            )}
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h2>Recommended next steps</h2></div>
          <div className="card-body">
            {summary.next_steps?.length ? (
              <ul className="small" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9, color: 'var(--ink-2)' }}>
                {summary.next_steps.map((n, i) => <li key={i}>{n}</li>)}
              </ul>
            ) : (
              <p className="small muted" style={{ margin: 0 }}>No specific actions are outstanding.</p>
            )}
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h2>Business impact</h2></div>
          <div className="card-body">
            <p className="small" style={{ margin: 0, color: 'var(--ink-2)' }}>{summary.business_impact}</p>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h2>Top priorities</h2></div>
        <div className="card-body stack" style={{ gap: 12 }}>
          {priorities.length === 0 && (
            <p className="small muted" style={{ margin: 0 }}>No priority issues were detected within the checks this audit performs.</p>
          )}
          {priorities.map((p) => (
            <div key={p.code} className="row" style={{ gap: 12, alignItems: 'flex-start' }}>
              <span className="action-num">{p.rank}</span>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div className="row row-wrap" style={{ gap: 6, marginBottom: 3 }}>
                  <Badge tone={SEVERITY_TONE(p.severity)}>{p.priority}</Badge>
                  <Badge tone="neutral">{p.category_label}</Badge>
                  <strong className="small">{p.title}</strong>
                </div>
                {p.recommendation && (
                  <p className="xsmall muted" style={{ margin: 0 }}><strong>Recommended action:</strong> {p.recommendation}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Category scores</h2>
          <div className="hint">Click a category to filter the findings below</div>
          <div className="spacer" />
          {activeCategory && (
            <button className="btn btn-sm" onClick={() => setActiveCategory(null)}>Show all</button>
          )}
        </div>
        <div className="card-body">
          <CategoryScorecards categories={sc.categories} onSelect={setActiveCategory} selected={activeCategory} />
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h2>Issues by severity</h2></div>
        <div className="card-body">
          <SeverityBreakdown
            critical={sc.severity_counts?.high || 0}
            high={sc.severity_counts?.medium || 0}
            warnings={sc.severity_counts?.low || 0}
            passed={checks.passed_count}
          />
        </div>
      </div>

      {visibleCategories.map((c) => (
        <div className="card" key={c.category}>
          <div className="card-head">
            <h2>{c.label}</h2>
            <div className="spacer" />
            <BandPill score={c.health} applicable={c.applicable !== false} />
          </div>
          <div className="card-body stack" style={{ gap: 12 }}>
            {c.applicable === false ? (
              <Empty title="Not applicable to this website">{c.not_applicable_reason}</Empty>
            ) : (
              <>
                {(byCategory[c.category] || []).length === 0 && (
                  <p className="small muted" style={{ margin: 0 }}>No evidence-backed issues were detected in this category.</p>
                )}
                {(byCategory[c.category] || []).map((f) => (
                  <FindingCard key={f.code} f={f} whyItMatters={c.why_it_matters} />
                ))}
              </>
            )}
          </div>
        </div>
      ))}

      <div className="card">
        <div className="card-head">
          <h2>Passed checks</h2>
          <div className="hint">{checks.passed_count} of {checks.total_checked}</div>
        </div>
        <div className="card-body">
          <div className="row row-wrap" style={{ gap: 8 }}>
            {checks.passed.map((p) => (
              <span key={p.id} className="passfail-chip">
                <IconCheck size={11} style={{ color: 'var(--ok)' }} /> {p.label}
              </span>
            ))}
          </div>
        </div>
      </div>

      {checks.not_verified.length > 0 && (
        <div className="card">
          <div className="card-head">
            <h2>Not verified</h2>
            <div className="hint">Never fabricated — reported honestly instead of guessed</div>
          </div>
          <div className="card-body stack" style={{ gap: 8 }}>
            {checks.not_verified.map((chk) => (
              <div key={chk.id} className="row row-wrap" style={{ gap: 8 }}>
                <Badge tone={describe(CHECK_STATUS, 'not_verified').tone}>{describe(CHECK_STATUS, 'not_verified').label}</Badge>
                <span className="small muted">{chk.label} — {chk.detail}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function FindingCard({ f, whyItMatters }) {
  return (
    <div className={`problem-item ${f.severity}`}>
      <div className="row row-wrap" style={{ gap: 7 }}>
        <Badge tone={SEVERITY_TONE(f.severity)}>{SEVERITY_LABEL[f.severity] || f.severity}</Badge>
      </div>
      <div className="t" style={{ marginTop: 6 }}>{f.title}</div>
      <div style={{ marginTop: 8 }}>
        <div className="xsmall muted strong" style={{ textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 2 }}>
          What we found
        </div>
        <div className="d">{f.detail}</div>
      </div>
      {whyItMatters && (
        <div style={{ marginTop: 8 }}>
          <div className="xsmall muted strong" style={{ textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 2 }}>
            Why it matters
          </div>
          <div className="d">{whyItMatters}</div>
        </div>
      )}
      {f.recommendation && (
        <div className="r" style={{ marginTop: 8 }}><strong>How to fix:</strong> {f.recommendation}</div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */

function Problems({ data }) {
  const problems = data.audit?.problems || []
  const recs = data.audit?.recommendations || []
  const recFor = (code) => recs.find((r) => r.problem_code === code)?.recommendation

  if (!problems.length) {
    return (
      <Empty title="No problems detected">
        {data.audit?.audit_error ||
          'The checks that ran found no evidence-backed problems on this website. Nothing has been invented to fill the gap.'}
      </Empty>
    )
  }

  return (
    <div className="stack" style={{ gap: 10 }}>
      {problems.map((p) => (
        <div key={p.code} className={`problem-item ${p.severity}`}>
          <div className="row row-wrap" style={{ gap: 7 }}>
            <Badge tone={p.severity === 'high' ? 'danger' : p.severity === 'medium' ? 'warn' : 'ok'}>
              {p.severity}
            </Badge>
            <Badge tone="neutral">{p.category_label || p.category}</Badge>
            {p.is_strong_signal && (
              <Badge tone="brand" title="Strong enough on its own to justify outreach">
                <IconSparkle size={10} /> strong signal
              </Badge>
            )}
          </div>
          <div className="t" style={{ marginTop: 6 }}>{p.title}</div>
          <div className="d">{p.detail}</div>
          {recFor(p.code) && <div className="r"><strong>Fix:</strong> {recFor(p.code)}</div>}
          {p.evidence && Object.keys(p.evidence).length > 0 && (
            <details style={{ marginTop: 8 }}>
              <summary className="xsmall muted" style={{ cursor: 'pointer' }}>Raw evidence</summary>
              <pre className="mono xsmall break" style={{ margin: '6px 0 0', whiteSpace: 'pre-wrap', color: 'var(--ink-3)' }}>
                {JSON.stringify(p.evidence, null, 2)}
              </pre>
            </details>
          )}
        </div>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ */

function formatFactValue(v) {
  if (v === true) return 'Yes'
  if (v === false) return 'No'
  if (v === null || v === undefined || v === '') return '—'
  if (Array.isArray(v)) {
    if (v.length === 0) return '—'
    const items = v.slice(0, 6).map((item) =>
      item && typeof item === 'object' ? item.url || item.title || item.label || JSON.stringify(item) : String(item),
    )
    return items.join(', ') + (v.length > 6 ? `, +${v.length - 6} more` : '')
  }
  if (typeof v === 'object') {
    if (v.measured === false) return `Not available — ${v.reason || 'not measured'}`
    const entries = Object.entries(v).slice(0, 4).map(([k, val]) => `${k}: ${val}`)
    return entries.join(', ') || '—'
  }
  return String(v).slice(0, 220)
}

/* ------------------------------------------------------------------ */

function Evidence({ data }) {
  const a = data.audit
  if (!a) return <Empty title="No audit stored">This lead has not been audited.</Empty>

  const ef = a.extra?.facts || {}
  const groups = [
    ['Technical', a.technical],
    ['Mobile', a.mobile],
    ['Conversion', a.conversion],
    ['Trust', a.trust],
    ['Content', a.content],
    ['Performance', a.performance],
    ['Security', ef.security],
    ['Accessibility', ef.accessibility],
    ['On-page SEO extras', ef.onpage],
    ['Local SEO', ef.local_seo],
    ['Off-page & authority', ef.offpage],
    ['Performance extras', ef.performance_extra],
  ].filter(([, v]) => v && Object.keys(v).length)

  return (
    <div className="stack">
      {a.pages?.length > 0 && (
        <div className="card">
          <div className="card-head"><h2>Pages reviewed</h2></div>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr><th>Type</th><th>URL</th><th className="num">Words</th><th className="num">ms</th></tr>
              </thead>
              <tbody>
                {a.pages.map((p, i) => (
                  <tr key={i}>
                    <td><Badge tone="neutral">{p.type}</Badge></td>
                    <td>
                      <a href={p.url} target="_blank" rel="noreferrer" className="truncate mono xsmall" title={p.url}>
                        {p.url}
                      </a>
                    </td>
                    <td className="num">{p.words ?? '—'}</td>
                    <td className="num">{p.elapsed_ms ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {groups.map(([name, facts]) => (
        <div className="card" key={name}>
          <div className="card-head"><h2>{name}</h2></div>
          <div className="card-body">
            <div className="kv">
              {Object.entries(facts).map(([k, v]) => (
                <div key={k}>
                  <div className="k">{k.replace(/_/g, ' ')}</div>
                  <div className="v break">{formatFactValue(v)}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      ))}

      <div className="card">
        <div className="card-head"><h2>Original CSV row</h2><div className="hint">Preserved exactly as supplied</div></div>
        <div className="card-body">
          <div className="kv">
            {Object.entries(data.raw || {}).map(([k, v]) => (
              <div key={k}>
                <div className="k">{k}</div>
                <div className="v break">{String(v || '—')}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
