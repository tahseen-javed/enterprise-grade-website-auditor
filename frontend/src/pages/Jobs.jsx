import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ActivityLog from '../components/ActivityLog'
import {
  IconAlert, IconPause, IconPlay, IconRefresh, IconStop, IconTrash, IconUpload,
} from '../components/icons'
import { NoJobYet } from '../components/shared'
import {
  Alert, Badge, Card, CardHead, Empty, Modal, Progress, Skeleton,
} from '../components/ui'
import { api } from '../lib/api'
import { dateTime, duration, num, timeAgo } from '../lib/format'
import { useApp, useFetch } from '../lib/store'

export default function Jobs() {
  const { jobs, refreshJobs, runningJobs, progress, toast, activeJobId, setActiveJobId } = useApp()
  const navigate = useNavigate()
  const [busy, setBusy] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(null)
  const [errorsFor, setErrorsFor] = useState(null)

  const act = async (id, fn, okMsg) => {
    setBusy(id)
    try {
      await fn(id)
      if (okMsg) toast(okMsg)
      await refreshJobs()
    } catch (err) {
      toast(err.message, 'err')
    } finally {
      setBusy(null)
    }
  }

  if (!jobs.length) return <div className="page"><Card><NoJobYet title="No jobs yet" /></Card></div>

  return (
    <div className="page stack">
      <div className="row">
        <span className="muted small">{jobs.length} job(s)</span>
        <div className="spacer" />
        <button className="btn btn-primary" onClick={() => navigate('/upload')}>
          <IconUpload size={14} /> New import
        </button>
      </div>

      {jobs.map((job) => {
        const running = runningJobs.includes(job.id)
        const live = progress[job.id]
        const c = job.counts
        const canResume = !running && c.pending + c.failed + c.running > 0

        return (
          <Card key={job.id}>
            <div className="card-head" style={{ alignItems: 'flex-start' }}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div className="row" style={{ gap: 8 }}>
                  <h2 className="truncate" title={job.name}>#{job.id} · {job.name}</h2>
                  <Badge tone={running ? 'info' : job.status === 'completed' ? 'ok' : job.status === 'failed' ? 'danger' : 'neutral'}>
                    {running ? 'running' : job.status}
                  </Badge>
                  {activeJobId === job.id && <Badge tone="brand">selected</Badge>}
                </div>
                <div className="xsmall muted" style={{ marginTop: 3 }}>
                  {job.source_filename} · created {timeAgo(job.created_at)}
                  {job.finished_at && ` · finished ${timeAgo(job.finished_at)}`}
                </div>
              </div>
              <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
                {activeJobId !== job.id && (
                  <button className="btn btn-sm" onClick={() => setActiveJobId(job.id)}>Select</button>
                )}
                {running ? (
                  <>
                    <button className="btn btn-sm" disabled={busy === job.id}
                            onClick={() => act(job.id, api.pauseJob, 'Paused')}>
                      <IconPause size={12} /> Pause
                    </button>
                    <button className="btn btn-sm" disabled={busy === job.id}
                            onClick={() => act(job.id, api.resumeJob, 'Resumed')}>
                      <IconPlay size={12} /> Continue
                    </button>
                    <button className="btn btn-sm btn-danger" disabled={busy === job.id}
                            onClick={() => act(job.id, api.cancelJob, 'Stopping…')}>
                      <IconStop size={12} /> Stop
                    </button>
                  </>
                ) : (
                  <>
                    {canResume && (
                      <button className="btn btn-sm btn-primary" disabled={busy === job.id}
                              onClick={() => act(job.id, api.resumeJob, 'Resumed where it stopped')}>
                        <IconPlay size={12} /> Resume ({num(c.pending + c.failed + c.running)} left)
                      </button>
                    )}
                    {c.failed > 0 && (
                      <button className="btn btn-sm" disabled={busy === job.id}
                              onClick={() => act(job.id, api.retryFailed, 'Failed leads requeued')}>
                        <IconRefresh size={12} /> Retry {c.failed} failed
                      </button>
                    )}
                    <button className="btn btn-sm btn-danger" onClick={() => setConfirmDelete(job)}>
                      <IconTrash size={12} />
                    </button>
                  </>
                )}
              </div>
            </div>

            <div className="card-body stack">
              <div>
                <div className="row" style={{ marginBottom: 6 }}>
                  <span className="small strong tabular">
                    {num(job.processed)} / {num(job.total)}
                  </span>
                  <span className="small muted">({job.percent}%)</span>
                  <div className="spacer" />
                  {live && (
                    <span className="xsmall muted tabular">
                      {live.rate_per_minute}/min
                      {live.eta_s != null && ` · ETA ${duration(live.eta_s)}`}
                      {` · workers ${live.workers_active}/${live.workers_total}`}
                    </span>
                  )}
                </div>
                <Progress value={job.percent} className="lg"
                          tone={job.status === 'completed' ? 'ok' : c.failed > 0 ? 'warn' : ''} />
              </div>

              <div className="row row-wrap small" style={{ gap: 'var(--sp-4)' }}>
                <span><span className="dot dot-ok" /> Done {num(c.completed)}</span>
                <span><span className="dot dot-neutral" /> Queued {num(c.pending)}</span>
                {c.running > 0 && <span><span className="dot dot-live" /> Running {num(c.running)}</span>}
                {c.failed > 0 && <span><span className="dot dot-danger" /> Failed {num(c.failed)}</span>}
                {c.skipped > 0 && <span><span className="dot dot-neutral" /> Skipped {num(c.skipped)}</span>}
                <div className="spacer" />
                {job.error_count > 0 && (
                  <button className="btn btn-sm" onClick={() => setErrorsFor(job)}>
                    <IconAlert size={12} /> {num(job.error_count)} error(s)
                  </button>
                )}
              </div>

              {!running && c.pending + c.failed > 0 && (
                <Alert tone="info">
                  This job is checkpointed. Resuming picks up only the {num(c.pending + c.failed)}{' '}
                  unfinished lead(s) — the {num(c.completed)} already done are never re-processed.
                </Alert>
              )}

              {job.last_error && <Alert tone="danger" title="Job error:">{job.last_error}</Alert>}
            </div>
          </Card>
        )
      })}

      <ActivityLog />

      <Modal
        open={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        title={`Delete job #${confirmDelete?.id}?`}
        footer={
          <>
            <div className="spacer" />
            <button className="btn" onClick={() => setConfirmDelete(null)}>Cancel</button>
            <button
              className="btn btn-danger"
              onClick={async () => {
                const id = confirmDelete.id
                setConfirmDelete(null)
                await act(id, api.deleteJob, 'Job deleted')
              }}
            >
              Delete permanently
            </button>
          </>
        }
      >
        <p>
          This removes <strong>{confirmDelete?.name}</strong> and all of its leads, audits, contacts
          and drafts from the database.
        </p>
        <p className="small muted" style={{ marginTop: 10 }}>
          Your original CSV file is untouched, and any exports already downloaded stay where they are.
        </p>
      </Modal>

      <JobErrors job={errorsFor} onClose={() => setErrorsFor(null)} />
    </div>
  )
}

function JobErrors({ job, onClose }) {
  const { data, loading } = useFetch(() => api.jobErrors(job.id, 300), [job?.id], { skip: !job })
  return (
    <Modal open={!!job} onClose={onClose} title={`Errors — job #${job?.id}`} wide>
      {loading && <Skeleton rows={5} />}
      {data && data.errors.length === 0 && <Empty title="No errors recorded" />}
      {data && data.errors.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr><th>Business</th><th>Stage</th><th>Code</th><th>Message</th><th>Retryable</th><th>When</th></tr>
            </thead>
            <tbody>
              {data.errors.map((e) => (
                <tr key={e.id}>
                  <td className="truncate" style={{ maxWidth: 150 }}>{e.business || '—'}</td>
                  <td><Badge tone="neutral">{e.stage}</Badge></td>
                  <td className="mono xsmall">{e.code}</td>
                  <td className="xsmall break" style={{ maxWidth: 320 }}>{e.message}</td>
                  <td>{e.retryable ? <Badge tone="warn">yes</Badge> : <Badge tone="neutral">no</Badge>}</td>
                  <td className="xsmall muted nowrap">{timeAgo(e.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  )
}
