import { useState } from 'react'
import { Link } from 'react-router-dom'
import { downloadUrl } from '../lib/api'
import {
  AUDIT_STATUS, CHANNEL, ITEM_STATUS, WEBSITE_STATUS, WHATSAPP_STATUS,
  describe, tierClass, timeAgo,
} from '../lib/format'
import { useApp } from '../lib/store'
import { IconExternal, IconSearch } from './icons'
import { Badge, Empty, ErrorState, Pagination, TableSkeleton } from './ui'

export function JobPicker({ compact }) {
  const { jobs, activeJobId, setActiveJobId, runningJobs } = useApp()
  if (!jobs.length) return null
  return (
    <select
      className={`select${compact ? ' input-sm' : ''}`}
      style={{ width: 'auto', minWidth: 200, maxWidth: 340 }}
      value={activeJobId ?? ''}
      onChange={(e) => setActiveJobId(e.target.value ? Number(e.target.value) : null)}
    >
      {jobs.map((j) => (
        <option key={j.id} value={j.id}>
          {runningJobs.includes(j.id) ? '● ' : ''}
          #{j.id} · {j.name}
        </option>
      ))}
    </select>
  )
}

export function NoJobYet({ title = 'No leads yet' }) {
  return (
    <Empty
      title={title}
      action={
        <Link className="btn btn-primary" to="/upload">
          Start a new audit
        </Link>
      }
    >
      Audit a single website URL, or upload a CSV/Excel file of businesses. Either way the app
      crawls each site, scores it and prepares personalised drafts — it never sends anything itself.
    </Empty>
  )
}

export function SearchBox({ value, onChange, placeholder = 'Search business, city, website…' }) {
  return (
    <div style={{ position: 'relative', flex: '1 1 240px', maxWidth: 380 }}>
      <IconSearch
        size={14}
        style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--ink-4)' }}
      />
      <input
        className="input"
        style={{ paddingLeft: 31 }}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  )
}

/**
 * The lead table used by Leads, Audits and the three channel pages.
 * `columns` selects which optional columns render, so each page shows what
 * matters for it without maintaining five near-identical tables.
 */
export function LeadTable({
  result, loading, error, reload, onOpen, page, onPage,
  columns = ['score', 'website', 'contact', 'channel', 'status'],
  emptyTitle = 'No leads match these filters',
  emptyHint = 'Try clearing the filters, or process a job first.',
}) {
  if (loading && !result) return <TableSkeleton rows={8} cols={6} />
  if (error) return <ErrorState error={error} onRetry={reload} />
  if (!result || !result.leads.length) return <Empty title={emptyTitle}>{emptyHint}</Empty>

  const show = (c) => columns.includes(c)

  return (
    <>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th style={{ width: 40 }}>Tier</th>
              <th>Business</th>
              {show('score') && <th className="num" style={{ width: 78 }}>Score</th>}
              {show('website') && <th style={{ width: 190 }}>Website</th>}
              {show('problems') && <th style={{ width: 250 }}>Top problem</th>}
              {show('contact') && <th style={{ width: 210 }}>Contact found</th>}
              {show('channel') && <th style={{ width: 130 }}>Channel</th>}
              {show('draft') && <th style={{ width: 280 }}>Draft preview</th>}
              {show('status') && <th style={{ width: 108 }}>Status</th>}
            </tr>
          </thead>
          <tbody>
            {result.leads.map((lead) => (
              <LeadRow key={lead.id} lead={lead} onOpen={onOpen} show={show} />
            ))}
          </tbody>
        </table>
      </div>
      <Pagination page={page} pages={result.pages} total={result.total} onPage={onPage} />
    </>
  )
}

function LeadRow({ lead, onOpen, show }) {
  const site = describe(WEBSITE_STATUS, lead.website_status)
  const chan = describe(CHANNEL, lead.best_channel)
  const status = describe(ITEM_STATUS, lead.status)
  const wa = lead.phone ? WHATSAPP_STATUS[lead.phone.whatsapp_status] : null
  const email = lead.emails?.[0]

  return (
    <tr className="clickable" onClick={() => onOpen(lead.id)}>
      <td>{lead.lead_tier ? <span className={`tier ${tierClass(lead.lead_tier)}`}>{lead.lead_tier}</span> : <span className="muted">—</span>}</td>
      <td>
        <div className="cell-title truncate" title={lead.name}>{lead.name}</div>
        <div className="cell-sub truncate">
          {[lead.category, lead.city, lead.country].filter(Boolean).join(' · ') || '—'}
        </div>
      </td>

      {show('score') && (
        <td className="num">
          {lead.score === null || lead.score === undefined ? (
            <span className="muted">—</span>
          ) : (
            <span className="strong tabular" style={{ color: scoreColor(lead.score) }}>{lead.score}</span>
          )}
          {lead.opportunity_tier && <div className="cell-sub">{lead.opportunity_tier}</div>}
          {lead.premium_score !== null && lead.premium_score !== undefined && (
            <div className="cell-sub">Health {lead.premium_score}/100</div>
          )}
        </td>
      )}

      {show('website') && (
        <td>
          <Badge tone={site.tone}>{site.label}</Badge>
          {lead.website_final && (
            <div className="cell-sub truncate" style={{ maxWidth: 180 }} title={lead.website_final}>
              {lead.website_final.replace(/^https?:\/\//, '').replace(/\/$/, '')}
            </div>
          )}
        </td>
      )}

      {show('problems') && (
        <td>
          {lead.problems?.length ? (
            <>
              <div className="truncate" style={{ maxWidth: 240 }} title={lead.problems[0].title}>
                {lead.problems[0].title}
              </div>
              {lead.problem_count > 1 && (
                <div className="cell-sub">+{lead.problem_count - 1} more</div>
              )}
            </>
          ) : (
            <span className="muted small">
              {lead.audit_status === 'no_clear_opportunity' ? 'No clear opportunity' : '—'}
            </span>
          )}
        </td>
      )}

      {show('contact') && (
        <td>
          {email ? (
            <div className="truncate mono xsmall" style={{ maxWidth: 200 }} title={email.email}>
              {email.email}
            </div>
          ) : lead.phone?.normalized ? (
            <div className="mono xsmall">{lead.phone.normalized}</div>
          ) : (
            <span className="muted small">None found</span>
          )}
          {wa && lead.best_channel === 'whatsapp' && (
            <div className="cell-sub">WhatsApp: {wa.label}</div>
          )}
          {email && <div className="cell-sub">{email.status.replace(/_/g, ' ')}</div>}
        </td>
      )}

      {show('channel') && (
        <td>
          <Badge tone={chan.tone} title={lead.channel_reason}>{chan.label}</Badge>
        </td>
      )}

      {show('draft') && (
        <td>
          {lead.draft_preview ? (
            <div className="xsmall muted" style={{ display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
              {lead.draft_preview}
            </div>
          ) : (
            <span className="muted small">No draft</span>
          )}
        </td>
      )}

      {show('status') && (
        <td>
          <Badge tone={status.tone}>{status.label}</Badge>
          {lead.processed_at && <div className="cell-sub">{timeAgo(lead.processed_at)}</div>}
        </td>
      )}
    </tr>
  )
}

function scoreColor(score) {
  if (score >= 75) return 'var(--danger)'
  if (score >= 60) return 'var(--warn)'
  if (score >= 40) return 'var(--brand)'
  return 'var(--ok)'
}

export function ReportLink({ leadId, hasReport }) {
  if (!hasReport) return <span className="muted small">—</span>
  return (
    <a
      className="btn btn-sm"
      href={downloadUrl.report(leadId)}
      target="_blank"
      rel="noreferrer"
      onClick={(e) => e.stopPropagation()}
    >
      <IconExternal size={12} /> Report
    </a>
  )
}
