import { useMemo, useState } from 'react'
import { clockTime } from '../lib/format'
import { useApp } from '../lib/store'
import { Empty } from './ui'
import { IconAlert } from './icons'

export default function ActivityLog({ jobId, height = 460, limit = 300 }) {
  const { log, connected } = useApp()
  const [filter, setFilter] = useState('all')

  const lines = useMemo(() => {
    let rows = log
    if (jobId) rows = rows.filter((e) => !e.job_id || e.job_id === jobId)
    if (filter === 'errors') rows = rows.filter((e) => e.level === 'error' || e.level === 'warn')
    return rows.slice(0, limit)
  }, [log, jobId, filter, limit])

  const errorCount = useMemo(
    () => log.filter((e) => e.level === 'error').length,
    [log],
  )

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div className="card-head">
        <h2>Live activity</h2>
        <span className={`dot ${connected ? 'dot-live' : 'dot-neutral'}`} title={connected ? 'Connected' : 'Reconnecting…'} />
        <div className="spacer" />
        <div className="seg">
          <button className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>
            All
          </button>
          <button className={filter === 'errors' ? 'active' : ''} onClick={() => setFilter('errors')}>
            Problems{errorCount ? ` (${errorCount})` : ''}
          </button>
        </div>
      </div>

      <div className="log" style={{ maxHeight: height }}>
        {lines.length === 0 ? (
          <Empty title={connected ? 'Nothing yet' : 'Not connected'}>
            {connected
              ? 'Events appear here in real time as leads are processed.'
              : 'Waiting for the backend event stream to connect.'}
          </Empty>
        ) : (
          lines.map((e, i) => (
            <div key={`${e.ts}-${i}`} className={`log-line ${e.level}`}>
              <span className="time">{clockTime(e.ts)}</span>
              <span className="who" title={e.business_name}>
                {e.business_name || '—'}
              </span>
              <span className="msg">
                {e.level === 'error' && <IconAlert size={11} style={{ marginRight: 5, verticalAlign: -1 }} />}
                {e.message}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
