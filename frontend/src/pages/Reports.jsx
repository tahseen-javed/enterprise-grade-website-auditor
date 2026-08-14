import { useState } from 'react'
import { IconDownload, IconExternal, IconReport } from '../components/icons'
import { JobPicker, NoJobYet } from '../components/shared'
import {
  Alert, Badge, Card, CardHead, Empty, Modal, Skeleton, Stat,
} from '../components/ui'
import { api, downloadUrl } from '../lib/api'
import { bytes, num, timeAgo } from '../lib/format'
import { useApp, useFetch } from '../lib/store'

export default function Reports() {
  const { activeJobId, jobs, runningJobs } = useApp()
  const [showColumns, setShowColumns] = useState(false)

  const job = jobs.find((j) => j.id === activeJobId)
  const running = activeJobId ? runningJobs.includes(activeJobId) : false

  const { data: stats } = useFetch(() => api.stats(activeJobId ?? undefined), [activeJobId])
  const { data: history, loading: histLoading, reload: reloadHistory } = useFetch(
    () => api.exportHistory(),
    [activeJobId],
  )
  const { data: columns } = useFetch(() => api.exportColumns(), [], { skip: !showColumns })

  if (!jobs.length) return <div className="page"><Card><NoJobYet title="Nothing to export yet" /></Card></div>

  const reportCount = stats ? stats.successful : 0

  return (
    <div className="page stack">
      <div className="row row-wrap">
        <JobPicker />
        {job && (
          <Badge tone={running ? 'info' : job.status === 'completed' ? 'ok' : 'neutral'}>
            {running ? 'still running' : job.status}
          </Badge>
        )}
        <div className="spacer" />
        <button className="btn btn-sm" onClick={reloadHistory}>Refresh</button>
      </div>

      {running && (
        <Alert tone="warn" title="This job is still running.">
          You can export now, but rows still being processed will have empty enrichment columns.
          Exporting again after it finishes gives you the complete file.
        </Alert>
      )}

      <div className="grid grid-4">
        <Stat label="Rows in export" value={num(job?.total)} accent="var(--brand)"
              meta="every original row, preserved" />
        <Stat label="Processed" value={num(stats?.processed)} accent="var(--ok)" />
        <Stat label="Audit reports" value={num(reportCount)} accent="var(--warn)"
              icon={<IconReport size={12} />} />
        <Stat label="Drafts written" value={num((stats?.drafts?.whatsapp || 0) + (stats?.drafts?.email || 0) + (stats?.drafts?.call || 0))}
              accent="var(--info)" meta="WhatsApp + email + call" />
      </div>

      <div className="grid grid-3">
        <ExportCard
          title="Final CSV"
          description="Your original file with the enrichment columns appended at the end. Same rows, same order, one business per row."
          href={activeJobId ? downloadUrl.csv(activeJobId) : null}
          label="Download CSV"
          note="UTF-8 with BOM, so Excel opens it correctly."
        />
        <ExportCard
          title="Excel workbook"
          description="The same data as the CSV, plus a second sheet documenting exactly what each appended column means."
          href={activeJobId ? downloadUrl.xlsx(activeJobId) : null}
          label="Download XLSX"
          note="Original columns are headed dark, appended columns indigo."
        />
        <ExportCard
          title="Audit reports"
          description="One self-contained HTML report per audited business, with the score breakdown, findings and the evidence behind each."
          href={activeJobId ? downloadUrl.reports(activeJobId) : null}
          label="Download ZIP"
          note={reportCount ? `${num(reportCount)} report(s) available.` : 'No reports generated yet.'}
          disabled={!reportCount}
        />
      </div>

      <Card>
        <CardHead
          title="What gets appended to your CSV"
          hint="Original columns are never modified, renamed or reordered"
        >
          <button className="btn btn-sm" onClick={() => setShowColumns(true)}>
            View full column reference
          </button>
        </CardHead>
        <div className="card-body">
          <div className="chip-row">
            {[
              'website_status', 'website_final', 'website_identity_confidence', 'email_1',
              'email_1_source', 'email_1_status', 'phone_normalized', 'phone_country',
              'whatsapp_status', 'whatsapp_url', 'website_score', 'opportunity_tier', 'lead_tier',
              'problems', 'recommendations', 'preferred_contact_channel', 'whatsapp_message',
              'email_subject', 'email_message', 'call_notes', 'audit_status', 'processed_at',
            ].map((c) => (
              <Badge key={c} tone="neutral" className="mono">{c}</Badge>
            ))}
          </div>
          <p className="xsmall muted" style={{ marginTop: 'var(--sp-4)' }}>
            If one of these names already exists in your file, the appended version is prefixed with
            <span className="mono"> audit_</span> so your own data is never overwritten.
          </p>
        </div>
      </Card>

      <Card>
        <CardHead title="Previously generated files" hint="Saved in the project's data/exports folder" />
        {histLoading && <Skeleton rows={4} />}
        {history && history.files.length === 0 && (
          <Empty title="No exports yet">Download a CSV or Excel file and it will be listed here.</Empty>
        )}
        {history && history.files.length > 0 && (
          <>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr><th>File</th><th style={{ width: 90 }}>Type</th><th className="num" style={{ width: 100 }}>Size</th><th style={{ width: 130 }}>Created</th></tr>
                </thead>
                <tbody>
                  {history.files.map((f) => (
                    <tr key={f.name}>
                      <td className="mono xsmall break">{f.name}</td>
                      <td><Badge tone="neutral">{f.kind.toUpperCase()}</Badge></td>
                      <td className="num">{bytes(f.size_bytes)}</td>
                      <td className="xsmall muted nowrap">{timeAgo(new Date(f.modified * 1000).toISOString())}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="card-foot mono xsmall break">{history.folder}</div>
          </>
        )}
      </Card>

      <Modal open={showColumns} onClose={() => setShowColumns(false)} title="Enrichment column reference" wide>
        {!columns && <Skeleton rows={6} />}
        {columns && (
          <>
            <Alert tone="info">{columns.note}</Alert>
            <div className="table-wrap" style={{ marginTop: 'var(--sp-4)' }}>
              <table className="data">
                <thead><tr><th style={{ width: 220 }}>Column</th><th>Meaning</th></tr></thead>
                <tbody>
                  {columns.columns.map((c) => (
                    <tr key={c}>
                      <td className="mono xsmall">{c}</td>
                      <td className="xsmall">
                        {columns.documentation[c] || <span className="muted">As named.</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Modal>
    </div>
  )
}

function ExportCard({ title, description, href, label, note, disabled }) {
  return (
    <Card>
      <div className="card-body stack" style={{ height: '100%' }}>
        <div>
          <h2 style={{ marginBottom: 6 }}>{title}</h2>
          <p className="small muted">{description}</p>
        </div>
        <div className="spacer" />
        {note && <p className="xsmall muted">{note}</p>}
        {href && !disabled ? (
          <a className="btn btn-primary btn-block" href={href} target="_blank" rel="noreferrer">
            <IconDownload size={14} /> {label}
          </a>
        ) : (
          <button className="btn btn-block" disabled>
            <IconDownload size={14} /> {label}
          </button>
        )}
      </div>
    </Card>
  )
}
