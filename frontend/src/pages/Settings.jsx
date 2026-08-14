import { useEffect, useMemo, useState } from 'react'
import { IconAlert, IconCheck, IconSettings } from '../components/icons'
import {
  Alert, Badge, Card, CardHead, ErrorState, Field, Skeleton, Switch,
} from '../components/ui'
import { api } from '../lib/api'
import { useApp, useFetch } from '../lib/store'

const TABS = [
  ['identity', 'Your identity'],
  ['scoring', 'Scoring'],
  ['engine', 'Crawler & speed'],
  ['integrations', 'Integrations'],
]

const TONE_HELP = {
  professional: 'Measured and courteous. A safe default for cold outreach.',
  friendly: 'Warmer and more casual, while staying respectful.',
  consultant: 'Positions you as a specialist reviewing their site.',
  founder: 'Direct, founder-to-founder, mentions your company by name.',
}

const CATEGORY_LABELS = {
  technical: 'Technical health',
  mobile: 'Mobile experience',
  conversion: 'Conversion readiness',
  trust: 'Trust & proof',
  contact: 'Contact accessibility',
  content: 'Content clarity',
}

export default function Settings() {
  const { toast, refreshSettings } = useApp()
  const [tab, setTab] = useState('identity')
  const { data, loading, error, reload } = useFetch(() => api.settings(), [])

  if (loading && !data) return <div className="page page-narrow"><Card><Skeleton rows={8} /></Card></div>
  if (error) return <div className="page page-narrow"><Card><ErrorState error={error} onRetry={reload} /></Card></div>

  const after = async () => {
    await refreshSettings()
    reload()
  }

  return (
    <div className="page page-narrow stack">
      {!data.profile_status.configured && (
        <Alert tone="warn" title="Outreach is paused until this is filled in.">
          Missing: <strong>{data.profile_status.missing_core.join(', ')}</strong>. Audits and contact
          discovery run regardless — only message writing is blocked, because the app will never
          invent your name, company or contact details.
        </Alert>
      )}

      <div className="seg" style={{ alignSelf: 'flex-start', flexWrap: 'wrap' }}>
        {TABS.map(([id, label]) => (
          <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>

      {tab === 'identity' && (
        <IdentityTab profile={data.profile} status={data.profile_status} tones={data.tones}
                     onSaved={after} toast={toast} />
      )}
      {tab === 'scoring' && <ScoringTab scoring={data.scoring} onSaved={after} toast={toast} />}
      {tab === 'engine' && <EngineTab engine={data.engine} onSaved={after} toast={toast} />}
      {tab === 'integrations' && <IntegrationsTab engine={data.engine} onSaved={after} toast={toast} />}
    </div>
  )
}

/* ====================================================================== */

function useDraft(initial) {
  const [draft, setDraft] = useState(initial)
  const [saving, setSaving] = useState(false)
  useEffect(() => setDraft(initial), [initial])
  const set = (key) => (value) => setDraft((d) => ({ ...d, [key]: value }))
  const dirty = useMemo(
    () => JSON.stringify(draft) !== JSON.stringify(initial),
    [draft, initial],
  )
  return { draft, setDraft, set, dirty, saving, setSaving }
}

function SaveBar({ dirty, saving, onSave, onReset, children }) {
  return (
    <div className="card-foot row">
      <span className="small">{children}</span>
      <div className="spacer" />
      {dirty && (
        <button className="btn btn-sm" onClick={onReset} disabled={saving}>Discard</button>
      )}
      <button className="btn btn-primary" onClick={onSave} disabled={!dirty || saving}>
        {saving ? <span className="spinner" /> : <IconCheck size={14} />}
        {saving ? 'Saving…' : dirty ? 'Save changes' : 'Saved'}
      </button>
    </div>
  )
}

/* ====================================================================== */

function IdentityTab({ profile, status, tones, onSaved, toast }) {
  const initial = useMemo(
    () => ({
      ...profile,
      target_countries: (profile.target_countries || []).join(', '),
      target_industries: (profile.target_industries || []).join(', '),
    }),
    [profile],
  )
  const { draft, setDraft, set, dirty, saving, setSaving } = useDraft(initial)

  const save = async () => {
    setSaving(true)
    try {
      await api.saveProfile({
        ...draft,
        target_countries: splitList(draft.target_countries),
        target_industries: splitList(draft.target_industries),
      })
      toast('Your details were saved')
      await onSaved()
    } catch (err) {
      toast(err.message, 'err')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <Card>
        <CardHead
          title="Outreach sender accounts"
          hint="The accounts your drafts are opened from — never fabricated, never substituted"
        />
        <div className="card-body stack">
          <div className="grid grid-2">
            <div className="row" style={{ gap: 10, alignItems: 'center' }}>
              <Badge tone={draft.whatsapp_number?.trim() ? 'ok' : 'warn'}>WhatsApp</Badge>
              <span className="mono small">{draft.whatsapp_number?.trim() || 'not set'}</span>
            </div>
            <div className="row" style={{ gap: 10, alignItems: 'center' }}>
              <Badge tone={draft.email?.trim() ? 'ok' : 'warn'}>Email</Badge>
              <span className="mono small">{draft.email?.trim() || 'not set'}</span>
            </div>
          </div>
          <p className="xsmall muted" style={{ margin: 0 }}>
            Every WhatsApp draft opens as a click-to-chat link sent from the number above; every
            email draft opens as a <span className="mono">mailto:</span> from the address above. The
            recipient's own number/email always comes from your CSV — these two fields only identify
            you.
          </p>
        </div>
      </Card>

      <Card>
        <CardHead
          title="Who the messages come from"
          hint="Stored locally in data/config/profile.json — never sent anywhere"
        />
        <div className="card-body stack">
          <div className="grid grid-2">
            <Field label="Your name" required
                   help="Used in greetings, call openers and the signature."
                   error={!draft.full_name?.trim() ? 'Required before any draft can be written.' : null}>
              <input className="input" value={draft.full_name || ''}
                     onChange={(e) => set('full_name')(e.target.value)} placeholder="e.g. Alex Morgan" />
            </Field>
            <Field label="Company or brand name" required
                   error={!draft.company_name?.trim() ? 'Required before any draft can be written.' : null}>
              <input className="input" value={draft.company_name || ''}
                     onChange={(e) => set('company_name')(e.target.value)} placeholder="e.g. Morgan Studio" />
            </Field>
            <Field label="WhatsApp sender number" required={false}
                   help="Include the country code. This is the account every WhatsApp draft is opened from."
                   error={status.missing_for_whatsapp?.length ? 'Not set — WhatsApp drafts still work, but your number will not appear in the signature.' : null}>
              <input className="input" value={draft.whatsapp_number || ''}
                     onChange={(e) => set('whatsapp_number')(e.target.value)} placeholder="+44 7700 900123" />
            </Field>
            <Field label="Email sender address"
                   help="The account every email draft is opened from, and where replies should land."
                   error={status.missing_for_email?.length ? 'Not set — email drafts will be skipped.' : null}>
              <input className="input" type="email" value={draft.email || ''}
                     onChange={(e) => set('email')(e.target.value)} placeholder="you@yourcompany.com" />
            </Field>
            <Field label="Your website or portfolio" help="Optional. Appears in the email signature.">
              <input className="input" value={draft.website_url || ''}
                     onChange={(e) => set('website_url')(e.target.value)} placeholder="https://yourcompany.com" />
            </Field>
            <Field label="Booking or calendar link" help="Optional. Offered as an easier alternative to replying.">
              <input className="input" value={draft.booking_url || ''}
                     onChange={(e) => set('booking_url')(e.target.value)} placeholder="https://cal.com/you/intro" />
            </Field>
          </div>
        </div>
        <SaveBar dirty={dirty} saving={saving} onSave={save} onReset={() => setDraft(initial)}>
          {status.configured ? 'Your identity is complete.' : 'Fill in the required fields to enable drafts.'}
        </SaveBar>
      </Card>

      <Card>
        <CardHead title="What you offer" hint="Shapes how the message describes your service" />
        <div className="card-body stack">
          <div className="grid grid-2">
            <Field label="Service name" required
                   help='What you sell, in your words. e.g. "website redesign".'
                   error={!draft.service_name?.trim() ? 'Required before any draft can be written.' : null}>
              <input className="input" value={draft.service_name || ''}
                     onChange={(e) => set('service_name')(e.target.value)} placeholder="website redesign" />
            </Field>
            <Field label="Who you target" help='Optional. e.g. "local service businesses".'>
              <input className="input" value={draft.target_service || ''}
                     onChange={(e) => set('target_service')(e.target.value)} placeholder="local service businesses" />
            </Field>
            <Field label="Preferred countries" help="Optional, comma separated. A note for yourself — it does not filter processing.">
              <input className="input" value={draft.target_countries || ''}
                     onChange={(e) => set('target_countries')(e.target.value)} placeholder="United Kingdom, Ireland" />
            </Field>
            <Field label="Preferred industries" help="Optional, comma separated.">
              <input className="input" value={draft.target_industries || ''}
                     onChange={(e) => set('target_industries')(e.target.value)} placeholder="plumbers, dentists, landscapers" />
            </Field>
          </div>

          <Field label="Tone of voice" help={TONE_HELP[draft.tone] || ''}>
            <div className="seg" style={{ flexWrap: 'wrap' }}>
              {(tones || []).map((t) => (
                <button key={t} className={draft.tone === t ? 'active' : ''}
                        onClick={() => set('tone')(t)} type="button">
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </button>
              ))}
            </div>
          </Field>

          <Field
            label="Email signature"
            help="Optional. Leave blank and one is built from the details above."
          >
            <textarea className="textarea" rows={4} value={draft.email_signature || ''}
                      onChange={(e) => set('email_signature')(e.target.value)}
                      placeholder={'Best regards,\nAlex Morgan\nMorgan Studio\nhttps://morganstudio.com'} />
          </Field>
        </div>
        <SaveBar dirty={dirty} saving={saving} onSave={save} onReset={() => setDraft(initial)}>
          Messages vary per lead based on the real problems found on their site.
        </SaveBar>
      </Card>
    </>
  )
}

const splitList = (value) =>
  String(value || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)

/* ====================================================================== */

function ScoringTab({ scoring, onSaved, toast }) {
  const initial = useMemo(
    () => ({
      weights: { ...scoring.weights },
      max_problems: scoring.max_problems,
      min_problems_for_outreach: scoring.min_problems_for_outreach,
    }),
    [scoring],
  )
  const { draft, setDraft, dirty, saving, setSaving } = useDraft(initial)
  const total = Object.values(draft.weights || {}).reduce((a, b) => a + Number(b || 0), 0)

  const save = async () => {
    setSaving(true)
    try {
      await api.saveScoring(draft)
      toast('Scoring weights saved')
      await onSaved()
    } catch (err) {
      toast(err.message, 'err')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <Alert tone="info" title="How the score works:">
        Each category starts at 100 points of health and loses points only for checks that actually
        failed. The opportunity score is <strong>100 minus that health</strong>, weighted by the values
        below — so a well-built site scores low and a neglected one scores high.
      </Alert>

      <Card>
        <CardHead title="Category weights" hint={`Currently totalling ${total}`} />
        <div className="card-body stack">
          {Object.entries(draft.weights || {}).map(([key, value]) => (
            <div key={key}>
              <div className="row" style={{ marginBottom: 4 }}>
                <label className="small strong">{CATEGORY_LABELS[key] || key}</label>
                <div className="spacer" />
                <span className="small tabular muted">
                  {value} ({total ? Math.round((value / total) * 100) : 0}% of the score)
                </span>
              </div>
              <input
                type="range" min="0" max="40" value={value}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, weights: { ...d.weights, [key]: Number(e.target.value) } }))
                }
                style={{ width: '100%', accentColor: 'var(--brand)' }}
              />
            </div>
          ))}
          {total === 0 && (
            <Alert tone="danger">
              All weights are zero, which would make every score 0. Give at least one category a weight.
            </Alert>
          )}
          <p className="xsmall muted">
            Weights are relative — they do not have to add up to 100. Measured performance
            (response time and, if configured, PageSpeed) is reported under Technical health.
          </p>
        </div>
        <SaveBar dirty={dirty} saving={saving} onSave={save} onReset={() => setDraft(initial)}>
          Applies to jobs started after saving; existing scores are not recalculated.
        </SaveBar>
      </Card>

      <Card>
        <CardHead title="Problem selection" />
        <div className="card-body grid grid-2">
          <Field label="Maximum problems to report" help="Keeps reports focused on the highest-impact findings.">
            <input className="input" type="number" min="1" max="15" value={draft.max_problems}
                   onChange={(e) => setDraft((d) => ({ ...d, max_problems: Number(e.target.value) }))} />
          </Field>
          <Field
            label="Minimum problems before outreach"
            help="Below this, the lead is marked no_clear_opportunity and left without a message rather than given an invented problem."
          >
            <input className="input" type="number" min="1" max="10" value={draft.min_problems_for_outreach}
                   onChange={(e) => setDraft((d) => ({ ...d, min_problems_for_outreach: Number(e.target.value) }))} />
          </Field>
        </div>
        <SaveBar dirty={dirty} saving={saving} onSave={save} onReset={() => setDraft(initial)}>
          Quality over volume.
        </SaveBar>
      </Card>
    </>
  )
}

/* ====================================================================== */

function EngineTab({ engine, onSaved, toast }) {
  const keys = [
    'workers', 'per_domain_concurrency', 'per_domain_delay_ms', 'max_pages_per_site',
    'max_crawl_depth', 'request_timeout_s', 'total_site_budget_s', 'max_retries',
    'backoff_base_s', 'respect_robots', 'verify_ssl', 'user_agent',
    'enable_website_discovery', 'min_identity_confidence', 'enable_mx_lookup', 'dns_timeout_s',
  ]
  const initial = useMemo(() => {
    const o = {}
    keys.forEach((k) => { o[k] = engine[k] })
    return o
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engine])
  const { draft, setDraft, set, dirty, saving, setSaving } = useDraft(initial)

  const save = async () => {
    setSaving(true)
    try {
      await api.saveEngine(draft)
      toast('Engine settings saved')
      await onSaved()
    } catch (err) {
      toast(err.message, 'err')
    } finally {
      setSaving(false)
    }
  }

  const num = (key, label, help, attrs = {}) => (
    <Field label={label} help={help}>
      <input className="input" type="number" value={draft[key] ?? ''} {...attrs}
             onChange={(e) => set(key)(e.target.value === '' ? '' : Number(e.target.value))} />
    </Field>
  )

  return (
    <>
      <Alert tone="info" title="Politeness is deliberate.">
        The crawler honours robots.txt, limits how many requests hit one host at a time, and waits
        between them. Making it faster by removing those limits would mean hammering other people's
        websites — so the controls are bounded.
      </Alert>

      <Card>
        <CardHead title="Concurrency" hint="How many businesses are processed at once" />
        <div className="card-body grid grid-2">
          {num('workers', 'Workers', 'How many businesses run in parallel. 1–20, default 5.',
               { min: 1, max: 20 })}
          {num('per_domain_concurrency', 'Requests per domain', 'Simultaneous requests to a single website. Keep this low.',
               { min: 1, max: 8 })}
          {num('per_domain_delay_ms', 'Delay between requests (ms)', 'Minimum wait between two hits on the same host.',
               { min: 0, max: 10000, step: 50 })}
          {num('max_retries', 'Retries', 'Retry attempts for temporary failures, with exponential backoff.',
               { min: 0, max: 6 })}
        </div>
        <SaveBar dirty={dirty} saving={saving} onSave={save} onReset={() => setDraft(initial)}>
          Takes effect on the next job you start.
        </SaveBar>
      </Card>

      <Card>
        <CardHead title="Crawl budget" hint="Stops one slow site from stalling a run" />
        <div className="card-body grid grid-2">
          {num('max_pages_per_site', 'Max pages per site', 'Homepage, contact, about, services, booking and so on.',
               { min: 1, max: 60 })}
          {num('max_crawl_depth', 'Max crawl depth', 'How many clicks from the homepage.', { min: 1, max: 5 })}
          {num('request_timeout_s', 'Request timeout (seconds)', '', { min: 3, max: 120, step: 1 })}
          {num('total_site_budget_s', 'Time budget per site (seconds)', 'Hard stop, whatever is left uncrawled.',
               { min: 10, max: 600, step: 5 })}
          {num('backoff_base_s', 'Backoff base (seconds)', 'Retry delay doubles from here.',
               { min: 0.2, max: 10, step: 0.1 })}
        </div>
        <SaveBar dirty={dirty} saving={saving} onSave={save} onReset={() => setDraft(initial)}>
          Lower budgets process more leads per hour but find fewer contact details.
        </SaveBar>
      </Card>

      <Card>
        <CardHead title="Behaviour" />
        <div className="card-body stack">
          <Switch checked={draft.respect_robots} onChange={set('respect_robots')}
                  label="Respect robots.txt (strongly recommended)" />
          {!draft.respect_robots && (
            <Alert tone="danger" title="Not recommended.">
              Ignoring robots.txt means crawling pages site owners asked automated tools to leave alone.
            </Alert>
          )}
          <Switch checked={draft.verify_ssl} onChange={set('verify_ssl')}
                  label="Verify SSL certificates" />
          <Switch checked={draft.enable_website_discovery} onChange={set('enable_website_discovery')}
                  label="Try to find a website when the CSV has none" />
          <p className="xsmall muted" style={{ marginTop: -6, marginLeft: 46 }}>
            A guessed domain is only accepted if the page itself corroborates the business — matching
            name, phone or address. Otherwise the lead is recorded as having no website rather than
            being given someone else's site.
          </p>
          <div className="grid grid-2">
            <Field label="Identity confidence threshold"
                   help={`A discovered site must score at least ${Math.round((draft.min_identity_confidence || 0) * 100)}% to be attached.`}>
              <input type="range" min="0.2" max="0.95" step="0.05"
                     value={draft.min_identity_confidence ?? 0.55}
                     onChange={(e) => set('min_identity_confidence')(Number(e.target.value))}
                     style={{ width: '100%', accentColor: 'var(--brand)' }} />
            </Field>
            {num('dns_timeout_s', 'DNS timeout (seconds)', 'Used for email MX lookups.', { min: 1, max: 20 })}
          </div>
          <Switch checked={draft.enable_mx_lookup} onChange={set('enable_mx_lookup')}
                  label="Check MX records when validating emails" />
          <Field label="User agent"
                 help="Sent with every request. Keep it honest and identifiable.">
            <input className="input mono xsmall" value={draft.user_agent || ''}
                   onChange={(e) => set('user_agent')(e.target.value)} />
          </Field>
        </div>
        <SaveBar dirty={dirty} saving={saving} onSave={save} onReset={() => setDraft(initial)}>
          Defaults are chosen to be safe on other people's servers.
        </SaveBar>
      </Card>
    </>
  )
}

/* ====================================================================== */

function IntegrationsTab({ engine, onSaved, toast }) {
  const keys = [
    'pagespeed_enabled', 'pagespeed_api_key', 'pagespeed_strategy',
    'playwright_enabled', 'llm_polish_enabled', 'llm_api_key', 'llm_model',
    'google_places_enabled', 'google_places_api_key',
  ]
  const initial = useMemo(() => {
    const o = {}
    keys.forEach((k) => { o[k] = engine[k] })
    return o
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engine])
  const { draft, setDraft, set, dirty, saving, setSaving } = useDraft(initial)

  const save = async () => {
    setSaving(true)
    try {
      // A masked value means "unchanged" - the backend ignores all-asterisk strings.
      await api.saveEngine(draft)
      toast('Integration settings saved')
      await onSaved()
    } catch (err) {
      toast(err.message, 'err')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <Alert tone="info" title="Everything here is optional.">
        The app works fully without any of it, and nothing is enabled until you supply your own key.
        Keys are stored server-side in <span className="mono">data/config/engine.json</span> and are
        never sent to the browser.
      </Alert>

      <Card>
        <CardHead title="Google PageSpeed Insights" hint="Real performance measurements">
          {engine.pagespeed_api_key_set && <Badge tone="ok"><IconCheck size={11} /> key stored</Badge>}
        </CardHead>
        <div className="card-body stack">
          <Switch checked={draft.pagespeed_enabled} onChange={set('pagespeed_enabled')}
                  label="Measure performance with PageSpeed Insights" />
          <p className="xsmall muted" style={{ marginLeft: 46, marginTop: -6 }}>
            Without this, performance findings come from a single server-side response-time
            measurement, and no PageSpeed score is ever claimed.
          </p>
          <div className="grid grid-2">
            <Field label="API key" help="Your own key from the Google Cloud console.">
              <input className="input mono xsmall" type="password"
                     value={draft.pagespeed_api_key || ''}
                     onChange={(e) => set('pagespeed_api_key')(e.target.value)}
                     placeholder={engine.pagespeed_api_key_set ? '•••••• stored' : 'AIza…'} />
            </Field>
            <Field label="Strategy" help="Mobile matches what most local customers use.">
              <select className="select" value={draft.pagespeed_strategy || 'mobile'}
                      onChange={(e) => set('pagespeed_strategy')(e.target.value)}>
                <option value="mobile">Mobile</option>
                <option value="desktop">Desktop</option>
              </select>
            </Field>
          </div>
          <Alert tone="warn">
            PageSpeed adds roughly 10–30 seconds per website and is rate limited. It is best used on a
            shortlist rather than a whole file.
          </Alert>
        </div>
        <SaveBar dirty={dirty} saving={saving} onSave={save} onReset={() => setDraft(initial)}>
          Check the System Health page to confirm the key works.
        </SaveBar>
      </Card>

      <Card>
        <CardHead title="Rendered mobile audit (Playwright)" />
        <div className="card-body stack">
          <Switch checked={draft.playwright_enabled} onChange={set('playwright_enabled')}
                  label="Use a real headless browser for mobile checks" />
          <Alert tone="warn" title="Requires a separate install.">
            Run <span className="mono">pip install playwright</span> then{' '}
            <span className="mono">playwright install chromium</span> (roughly 300 MB) inside
            <span className="mono"> backend/.venv</span>. Until then, leave this off — mobile findings
            are derived from the page's HTML and inline CSS and are labelled as such everywhere they
            appear, rather than being presented as rendered measurements.
          </Alert>
        </div>
        <SaveBar dirty={dirty} saving={saving} onSave={save} onReset={() => setDraft(initial)}>
          Off by default.
        </SaveBar>
      </Card>

      <Card>
        <CardHead title="Claude polish for drafts" hint="Optional rewrite pass">
          {engine.llm_api_key_set && <Badge tone="ok"><IconCheck size={11} /> key stored</Badge>}
        </CardHead>
        <div className="card-body stack">
          <Switch checked={draft.llm_polish_enabled} onChange={set('llm_polish_enabled')}
                  label="Enable the optional language-model polish pass" />
          <div className="grid grid-2">
            <Field label="Anthropic API key">
              <input className="input mono xsmall" type="password" value={draft.llm_api_key || ''}
                     onChange={(e) => set('llm_api_key')(e.target.value)}
                     placeholder={engine.llm_api_key_set ? '•••••• stored' : 'sk-ant-…'} />
            </Field>
            <Field label="Model">
              <input className="input mono xsmall" value={draft.llm_model || ''}
                     onChange={(e) => set('llm_model')(e.target.value)} placeholder="claude-sonnet-5" />
            </Field>
          </div>
          <Alert tone="info">
            Drafts are written by the deterministic engine from measured findings, which is why they
            cannot invent a problem. This flag and key are stored for that optional pass; the current
            build always uses the deterministic generator.
          </Alert>
        </div>
        <SaveBar dirty={dirty} saving={saving} onSave={save} onReset={() => setDraft(initial)}>
          Costs apply per lead if you enable a model.
        </SaveBar>
      </Card>

      <Card>
        <CardHead title="Google Places" hint="Not required — your CSV is the source of truth">
          {engine.google_places_api_key_set && <Badge tone="ok"><IconCheck size={11} /> key stored</Badge>}
        </CardHead>
        <div className="card-body stack">
          <Switch checked={draft.google_places_enabled} onChange={set('google_places_enabled')}
                  label="Enable Google Places enrichment" />
          <Field label="API key">
            <input className="input mono xsmall" type="password" value={draft.google_places_api_key || ''}
                   onChange={(e) => set('google_places_api_key')(e.target.value)}
                   placeholder={engine.google_places_api_key_set ? '•••••• stored' : 'AIza…'} />
          </Field>
          <Alert tone="warn" title="Terms apply.">
            If you enable this, Google Maps Platform terms govern how their content may be stored,
            cached and displayed. The app never requires it — processing your CSV works without any
            Google API.
          </Alert>
        </div>
        <SaveBar dirty={dirty} saving={saving} onSave={save} onReset={() => setDraft(initial)}>
          Disabled by default.
        </SaveBar>
      </Card>
    </>
  )
}
