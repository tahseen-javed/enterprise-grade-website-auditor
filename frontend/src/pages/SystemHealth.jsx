import { useEffect, useState } from 'react'
import { IconAlert, IconCheck, IconInfo, IconRefresh } from '../components/icons'
import { Alert, Badge, Card, CardHead, ErrorState, Skeleton, Stat } from '../components/ui'
import { api } from '../lib/api'
import { num } from '../lib/format'
import { useApp, useFetch } from '../lib/store'

const COMPONENT_LABELS = {
  backend: ['Backend API', 'The FastAPI process serving this dashboard'],
  database: ['Database', 'SQLite store holding jobs, leads, audits and drafts'],
  crawler: ['Crawler', 'HTML parser plus the politeness and concurrency limits'],
  dns: ['DNS resolution', 'Needed to verify email domains have MX records'],
  outbound_http: ['Outbound HTTPS', 'Whether this machine can reach external websites'],
  email_validator: ['Validation libraries', 'Email syntax checking and phone number parsing'],
  browser_engine: ['Browser engine', 'Optional rendered mobile audit via Playwright'],
  pagespeed: ['PageSpeed Insights', 'Optional real performance measurement'],
  export_engine: ['Export engine', 'CSV, Excel and HTML report generation'],
  file_system: ['File system', 'Data, upload, export and report folders'],
  ports: ['Ports', 'Local ports this app is bound to'],
  outreach_profile: ['Outreach identity', 'Your name, company and service'],
  event_stream: ['Live event stream', 'Server-sent events powering the live dashboard'],
}

const TONE = { healthy: 'ok', warning: 'warn', error: 'danger', disabled: 'neutral' }
const LABEL = { healthy: 'Healthy', warning: 'Warning', error: 'Error', disabled: 'Not configured' }

export default function SystemHealth() {
  const { connected } = useApp()
  const [auto, setAuto] = useState(false)
  const { data, loading, error, reload } = useFetch(() => api.systemHealth(), [])

  useEffect(() => {
    if (!auto) return
    const id = setInterval(reload, 10000)
    return () => clearInterval(id)
  }, [auto, reload])

  if (loading && !data) return <div className="page"><Card><Skeleton rows={9} /></Card></div>
  if (error) {
    return (
      <div className="page stack">
        <Alert tone="danger" title="Could not reach the backend.">
          {error.message}
        </Alert>
        <Card><ErrorState error={error} onRetry={reload} /></Card>
      </div>
    )
  }

  const entries = Object.entries(data.components)
  const counts = entries.reduce(
    (acc, [, c]) => {
      acc[c.status] = (acc[c.status] || 0) + 1
      return acc
    },
    {},
  )
  const problems = entries.filter(([, c]) => c.status === 'error' || c.status === 'warning')

  return (
    <div className="page stack">
      <div className="row row-wrap">
        <Badge tone={TONE[data.overall]}>
          {data.overall === 'healthy' ? <IconCheck size={12} /> : <IconAlert size={12} />}
          {data.overall === 'healthy'
            ? 'All systems healthy'
            : data.overall === 'warning'
              ? 'Running with warnings'
              : 'Attention needed'}
        </Badge>
        <span className={`dot ${connected ? 'dot-live' : 'dot-danger'}`} />
        <span className="small muted">
          {connected ? 'Live stream connected' : 'Live stream disconnected'}
        </span>
        <div className="spacer" />
        <button className={`btn btn-sm${auto ? ' btn-ok' : ''}`} onClick={() => setAuto((v) => !v)}>
          {auto ? 'Auto-refresh on' : 'Auto-refresh off'}
        </button>
        <button className="btn btn-sm" onClick={reload} disabled={loading}>
          {loading ? <span className="spinner" /> : <IconRefresh size={13} />} Re-check
        </button>
      </div>

      {problems.length > 0 && (
        <Alert tone={problems.some(([, c]) => c.status === 'error') ? 'danger' : 'warn'}
               title={`${problems.length} component(s) need attention:`}>
          {problems.map(([key]) => (COMPONENT_LABELS[key]?.[0] || key)).join(', ')}. Details below —
          nothing is hidden.
        </Alert>
      )}

      <div className="grid grid-4">
        <Stat label="Healthy" value={num(counts.healthy || 0)} accent="var(--ok)" />
        <Stat label="Warnings" value={num(counts.warning || 0)} accent="var(--warn)" />
        <Stat label="Errors" value={num(counts.error || 0)} accent="var(--danger)" />
        <Stat label="Not configured" value={num(counts.disabled || 0)} accent="var(--neutral)"
              meta="optional integrations" />
      </div>

      <Card>
        <CardHead title="Components" hint="Every check reports its real state" />
        <div>
          {entries.map(([key, comp]) => {
            const [label, description] = COMPONENT_LABELS[key] || [key.replace(/_/g, ' '), '']
            return (
              <div className="health-item" key={key}>
                <span
                  className={`dot dot-${
                    comp.status === 'healthy' ? 'ok'
                      : comp.status === 'warning' ? 'warn'
                        : comp.status === 'error' ? 'danger' : 'neutral'
                  }`}
                  style={{ marginTop: 6 }}
                />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="row" style={{ gap: 8 }}>
                    <span className="name">{label}</span>
                    <Badge tone={TONE[comp.status]}>{LABEL[comp.status] || comp.status}</Badge>
                  </div>
                  {description && <div className="detail">{description}</div>}
                  <div className="detail break" style={{ color: 'var(--ink-2)', marginTop: 3 }}>
                    {comp.detail}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </Card>

      <div className="grid grid-2">
        <Card>
          <CardHead title="Ports" hint="Fixed and configurable" />
          <div className="card-body">
            <div className="kv">
              <div>
                <div className="k">Backend</div>
                <div className="v mono">
                  http://127.0.0.1:{data.ports.backend}
                </div>
              </div>
              <div>
                <div className="k">Frontend</div>
                <div className="v mono">
                  http://localhost:{data.ports.frontend}
                </div>
              </div>
            </div>
            <p className="xsmall muted" style={{ marginTop: 'var(--sp-4)' }}>
              Change these with WAE_BACKEND_PORT / WAE_FRONTEND_PORT before starting, if something
              else on this machine already uses them.
            </p>
          </div>
        </Card>

        <Card>
          <CardHead title="Engine configuration" hint="Currently active values" />
          <div className="card-body">
            <div className="kv">
              <div><div className="k">Workers</div><div className="v tabular">{data.engine.workers}</div></div>
              <div><div className="k">Per-domain limit</div><div className="v tabular">{data.engine.per_domain_concurrency}</div></div>
              <div><div className="k">Politeness delay</div><div className="v tabular">{data.engine.per_domain_delay_ms} ms</div></div>
              <div><div className="k">Pages per site</div><div className="v tabular">{data.engine.max_pages_per_site}</div></div>
              <div><div className="k">Request timeout</div><div className="v tabular">{data.engine.request_timeout_s}s</div></div>
              <div>
                <div className="k">robots.txt</div>
                <div className="v">
                  <Badge tone={data.engine.respect_robots ? 'ok' : 'danger'}>
                    {data.engine.respect_robots ? 'Respected' : 'Ignored'}
                  </Badge>
                </div>
              </div>
              <div>
                <div className="k">MX lookups</div>
                <div className="v">
                  <Badge tone={data.engine.enable_mx_lookup ? 'ok' : 'neutral'}>
                    {data.engine.enable_mx_lookup ? 'On' : 'Off'}
                  </Badge>
                </div>
              </div>
              <div>
                <div className="k">Site discovery</div>
                <div className="v">
                  <Badge tone={data.engine.enable_website_discovery ? 'ok' : 'neutral'}>
                    {data.engine.enable_website_discovery ? 'On' : 'Off'}
                  </Badge>
                </div>
              </div>
            </div>
          </div>
        </Card>
      </div>

      <Card>
        <CardHead title="Data locations" hint="Everything stays on this machine" />
        <div className="card-body">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
            {Object.entries(data.paths).map(([key, path]) => (
              <div key={key}>
                <div className="k xsmall muted strong" style={{ textTransform: 'uppercase', letterSpacing: '0.07em' }}>
                  {key}
                </div>
                <div className="mono xsmall break">{path}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="card-foot row">
          <IconInfo size={13} />
          <span>
            No lead data, audit result or contact detail is transmitted anywhere. Outbound requests go
            only to the business websites being audited, DNS for email verification, and any optional
            API you configured yourself.
          </span>
        </div>
      </Card>
    </div>
  )
}
