import { useState } from 'react'
import { api, downloadUrl } from '../lib/api'
import {
  AUDIT_CATEGORY_LABELS, AUDIT_STATUS, CHANNEL, EMAIL_STATUS, LINKEDIN_STATUS, PHONE_STATUS,
  WEBSITE_STATUS, WHATSAPP_STATUS, dateTime, describe, tierClass,
} from '../lib/format'
import { useFetch } from '../lib/store'
import { BandPill, CategoryScorecards, ScoreDial, SeverityBreakdown } from './charts'
import {
  IconAlert, IconCheck, IconExternal, IconGlobe, IconLinkedIn, IconMail, IconPhone,
  IconSparkle, IconWhatsApp,
} from './icons'
import { Alert, Badge, CopyButton, Drawer, Empty, ErrorState, KV, Progress, Skeleton } from './ui'

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
  const chan = describe(CHANNEL, data.best_channel)
  const wa = data.phone ? WHATSAPP_STATUS[data.phone.whatsapp_status] : null

  return (
    <>
      <div className="card card-pad">
        <div className="row" style={{ gap: 'var(--sp-5)', alignItems: 'center', flexWrap: 'wrap' }}>
          <ScoreDial score={data.score} size={112} />
          <div style={{ flex: 1, minWidth: 210 }}>
            <div className="row row-wrap" style={{ gap: 7, marginBottom: 10 }}>
              <Badge tone={site.tone}>{site.label}</Badge>
              {data.opportunity_tier && <Badge tone="brand">{data.opportunity_tier} opportunity</Badge>}
              <Badge tone={chan.tone}>{chan.label}</Badge>
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

      {data.channel_reason && (
        <Alert tone="info" title="Why this channel:">{data.channel_reason}</Alert>
      )}

      <div className="card">
        <div className="card-head"><h2>Contact</h2></div>
        <div className="card-body stack">
          {data.phone ? (
            <div>
              <div className="row row-wrap" style={{ gap: 8 }}>
                <IconPhone size={14} />
                <span className="strong mono">{data.phone.normalized || data.phone.raw}</span>
                <Badge tone={describe(PHONE_STATUS, data.phone.status).tone}>
                  {describe(PHONE_STATUS, data.phone.status).label}
                </Badge>
                {data.phone.country && <Badge tone="neutral">{data.phone.country}</Badge>}
                {data.phone.type && <Badge tone="neutral">{data.phone.type.replace(/_/g, ' ')}</Badge>}
                <div className="spacer" />
                <CopyButton text={data.phone.normalized || data.phone.raw} />
              </div>
              {data.phone.raw !== data.phone.normalized && (
                <div className="xsmall muted" style={{ marginTop: 4 }}>
                  Original value in your CSV: <span className="mono">{data.phone.raw}</span>
                </div>
              )}
              <div className="row" style={{ gap: 8, marginTop: 9 }}>
                <IconWhatsApp size={14} />
                <Badge tone={wa?.tone || 'neutral'}>{wa?.label || data.phone.whatsapp_status}</Badge>
                {data.phone.whatsapp_url && (
                  <a className="btn btn-sm btn-wa" href={data.phone.whatsapp_url} target="_blank" rel="noreferrer">
                    <IconExternal size={12} /> Open chat
                  </a>
                )}
              </div>
              <p className="xsmall muted" style={{ marginTop: 5 }}>{data.phone.whatsapp_reason}</p>
            </div>
          ) : (
            <p className="small muted">No phone number was supplied for this business.</p>
          )}

          <div style={{ borderTop: '1px solid var(--line)', paddingTop: 'var(--sp-4)' }}>
            {data.emails.length ? (
              data.emails.map((e) => (
                <div key={e.email} style={{ marginBottom: 12 }}>
                  <div className="row row-wrap" style={{ gap: 8 }}>
                    <IconMail size={14} />
                    <span className="strong mono break">{e.email}</span>
                    <Badge tone={describe(EMAIL_STATUS, e.status).tone} title={describe(EMAIL_STATUS, e.status).help}>
                      {describe(EMAIL_STATUS, e.status).label}
                    </Badge>
                    {e.is_role && <Badge tone="neutral">role address</Badge>}
                    <div className="spacer" />
                    <CopyButton text={e.email} />
                  </div>
                  <div className="xsmall muted" style={{ marginTop: 3 }}>
                    Found on{' '}
                    <a href={e.source_url} target="_blank" rel="noreferrer">{e.page_type || 'page'}</a>{' '}
                    via {e.source_type}
                    {e.mx_records?.length ? ` · MX: ${e.mx_records.slice(0, 2).join(', ')}` : ''}
                  </div>
                </div>
              ))
            ) : (
              <p className="small muted">
                No public email address was found on this website. Nothing was guessed.
              </p>
            )}
          </div>

          <div style={{ borderTop: '1px solid var(--line)', paddingTop: 'var(--sp-4)' }}>
            {data.linkedin_url ? (
              <div className="row row-wrap" style={{ gap: 8 }}>
                <IconLinkedIn size={14} />
                <a href={data.linkedin_url} target="_blank" rel="noreferrer" className="strong mono break">
                  {data.linkedin_url}
                </a>
                <Badge tone="linkedin">Company page</Badge>
                <div className="spacer" />
                <CopyButton text={data.linkedin_url} />
              </div>
            ) : (
              <p className="small muted">
                {describe(LINKEDIN_STATUS, data.linkedin_status).label === 'Not checked'
                  ? 'LinkedIn was not looked for — WhatsApp or email was already usable for this lead.'
                  : 'No LinkedIn company page was found linked from this website. Nothing was guessed.'}
              </p>
            )}
          </div>
        </div>
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
  const extra = data.audit?.extra || {}
  const sc = extra.scorecard || {}
  const findings = extra.findings || []
  const pf = sc.pass_fail || { passed: [], passed_count: 0, total_checked: 0 }

  if (!sc.categories?.length) {
    return (
      <Empty title="No premium scorecard for this lead">
        {data.audit?.audit_error ||
          'This audit ran before the premium scorecard existed, or the site could not be crawled.'}
      </Empty>
    )
  }

  const legacyProblems = data.audit?.problems || []
  const severity = { high: 0, medium: 0, low: 0 }
  for (const p of legacyProblems) if (p.severity in severity) severity[p.severity] += 1
  for (const f of findings) if (f.severity in severity) severity[f.severity] += 1

  const byCategory = {}
  for (const f of findings) {
    (byCategory[f.category] ||= []).push(f)
  }

  return (
    <div className="stack">
      <div className="card card-pad">
        <div className="row" style={{ gap: 'var(--sp-5)', alignItems: 'center', flexWrap: 'wrap' }}>
          <ScoreDial score={sc.overall_score} size={112} label="health" />
          <div style={{ flex: 1, minWidth: 220 }}>
            <div className="row row-wrap" style={{ gap: 7, marginBottom: 10 }}>
              <BandPill score={sc.overall_score} />
              <Badge tone="neutral">{pf.passed_count}/{pf.total_checked} checks passed</Badge>
            </div>
            <p className="small muted" style={{ margin: 0 }}>
              This is a health score — higher is better, unlike the opportunity score on Overview.
              Technical SEO, on-page SEO, off-page/authority, performance, accessibility, security,
              UX and conversion are each scored independently, then weighted into the figure above.
            </p>
          </div>
        </div>
      </div>

      {data.has_report && (
        <a className="btn btn-block btn-primary" href={downloadUrl.report(data.id)} target="_blank" rel="noreferrer">
          <IconExternal size={13} /> Open the full premium report
        </a>
      )}

      <div className="card">
        <div className="card-head"><h2>Category scorecards</h2></div>
        <div className="card-body">
          <CategoryScorecards categories={sc.categories} />
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h2>Issue severity</h2></div>
        <div className="card-body">
          <SeverityBreakdown
            critical={severity.high} high={severity.medium} warnings={severity.low}
            passed={pf.passed_count}
          />
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>New in the premium audit</h2>
          <div className="hint">Security, accessibility, on-page and off-page extras, performance extras</div>
        </div>
        <div className="card-body stack" style={{ gap: 14 }}>
          {findings.length === 0 && (
            <p className="small muted" style={{ margin: 0 }}>
              No issues were detected in these categories.
            </p>
          )}
          {Object.entries(byCategory).map(([cat, items]) => (
            <div key={cat}>
              <div className="small strong" style={{ marginBottom: 6 }}>
                {AUDIT_CATEGORY_LABELS[cat] || cat} <span className="muted">— {items.length}</span>
              </div>
              <div className="stack" style={{ gap: 8 }}>
                {items.map((f) => (
                  <div key={f.code} className={`problem-item ${f.severity}`}>
                    <div className="row row-wrap" style={{ gap: 7 }}>
                      <Badge tone={f.severity === 'high' ? 'danger' : f.severity === 'medium' ? 'warn' : 'ok'}>
                        {f.severity}
                      </Badge>
                    </div>
                    <div className="t" style={{ marginTop: 6 }}>{f.title}</div>
                    <div className="d">{f.detail}</div>
                    {f.recommendation && <div className="r"><strong>Fix:</strong> {f.recommendation}</div>}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Passed checks</h2>
          <div className="hint">{pf.passed_count} of {pf.total_checked}</div>
        </div>
        <div className="card-body">
          <div className="row row-wrap" style={{ gap: 8 }}>
            {(pf.passed || []).map((p) => (
              <span key={p.id} className="passfail-chip">
                <IconCheck size={11} style={{ color: 'var(--ok)' }} /> {p.label}
              </span>
            ))}
          </div>
        </div>
      </div>
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
