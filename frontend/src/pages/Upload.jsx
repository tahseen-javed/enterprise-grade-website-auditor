import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { IconAudit } from '../components/icons'
import { Alert, Card, CardHead, Field } from '../components/ui'
import { api } from '../lib/api'
import { useApp } from '../lib/store'

export default function Upload() {
  const { toast, refreshJobs, setActiveJobId } = useApp()
  const navigate = useNavigate()

  const [siteUrl, setSiteUrl] = useState('')
  const [siteLabel, setSiteLabel] = useState('')
  const [auditing, setAuditing] = useState(false)
  const [error, setError] = useState(null)

  const runQuickAudit = async () => {
    if (!siteUrl.trim()) return
    setError(null)
    setAuditing(true)
    try {
      const result = await api.quickAudit(siteUrl.trim(), siteLabel.trim())
      await refreshJobs()
      setActiveJobId(result.job_id)
      toast(`Audit started for ${result.url}`)
      navigate('/audits')
    } catch (err) {
      setError(err)
      toast(err.message, 'err')
    } finally {
      setAuditing(false)
    }
  }

  return (
    <div className="page page-narrow stack">
      {error && <Alert tone="danger" title="Could not start the audit:">{error.message}</Alert>}

      <Card>
        <CardHead title="Audit a website" hint="Crawled politely and scored across every category" />
        <div className="card-body stack">
          <Field label="Website URL" required help="Include the domain, e.g. example.com or https://example.com">
            <input
              className="input"
              value={siteUrl}
              placeholder="https://example.com"
              onChange={(e) => setSiteUrl(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && runQuickAudit()}
            />
          </Field>
          <Field label="Label (optional)" help="Just a name so you can find this audit later — defaults to the domain">
            <input
              className="input"
              value={siteLabel}
              placeholder="Acme Roofing"
              onChange={(e) => setSiteLabel(e.target.value)}
            />
          </Field>
        </div>
        <div className="card-foot row">
          <span className="small muted">
            The site is crawled politely (robots.txt honoured) and audited across technical SEO,
            on-page SEO, performance, accessibility, security, UX and conversion.
          </span>
          <div className="spacer" />
          <button className="btn btn-primary btn-lg" onClick={runQuickAudit} disabled={!siteUrl.trim() || auditing}>
            {auditing ? <span className="spinner" /> : <IconAudit size={14} />}
            Start audit
          </button>
        </div>
      </Card>

      <Card>
        <CardHead title="What happens next" />
        <div className="card-body">
          <ol className="small" style={{ margin: 0, paddingLeft: 20, lineHeight: 2, color: 'var(--ink-2)' }}>
            <li>The site is fetched and crawled politely (robots.txt honoured, rate limited).</li>
            <li>Technical SEO, on-page SEO, performance, accessibility, security, UX and conversion are all checked.</li>
            <li>Off-page/authority signals are reported where measurable from the site itself — backlink
                and domain-authority data are clearly labelled unavailable rather than guessed.</li>
            <li>A 9-part scorecard and a full, evidence-backed findings report are generated.</li>
            <li>Open it from Website Audits once it finishes — usually well under a minute.</li>
          </ol>
        </div>
      </Card>
    </div>
  )
}
