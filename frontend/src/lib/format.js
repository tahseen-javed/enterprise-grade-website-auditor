// Presentation helpers. These translate the backend's deliberately precise
// status vocabulary into wording a person can read, without softening what
// the status actually means.

export const num = (v) =>
  v === null || v === undefined ? '—' : Number(v).toLocaleString()

export const pct = (v, digits = 0) =>
  v === null || v === undefined ? '—' : `${Number(v).toFixed(digits)}%`

export function duration(seconds) {
  if (seconds === null || seconds === undefined) return '—'
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${s % 60}s`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m`
}

export function timeAgo(iso) {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const diff = Math.round((Date.now() - then) / 1000)
  if (diff < 45) return 'just now'
  if (diff < 90) return 'a minute ago'
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`
  if (diff < 604800) return `${Math.round(diff / 86400)}d ago`
  return new Date(iso).toLocaleDateString()
}

export const clockTime = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? ''
    : d.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export const dateTime = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString()
}

export const bytes = (n) => {
  if (!n && n !== 0) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1048576).toFixed(1)} MB`
}

// ---------------------------------------------------------------------------
// Status vocabularies
// ---------------------------------------------------------------------------

export const WHATSAPP_STATUS = {
  confirmed_on_website: {
    label: 'Confirmed on site',
    tone: 'ok',
    help: 'A WhatsApp link for this exact number is published on the business website. This is real evidence.',
  },
  usable_unverified: {
    label: 'Usable (unverified)',
    tone: 'wa',
    help: 'The number is valid, international, and of a type that can use WhatsApp, so a chat link is prepared. Whether the number actually has WhatsApp was NOT verified.',
  },
  unlikely: {
    label: 'Unlikely (landline)',
    tone: 'neutral',
    help: 'The number is a landline or similar line type that normally cannot use WhatsApp.',
  },
  invalid_number: {
    label: 'Number invalid',
    tone: 'danger',
    help: 'The phone number could not be normalized to international format, so no chat link was built.',
  },
  no_phone: { label: 'No phone', tone: 'neutral', help: 'No phone number was supplied for this business.' },
  not_checked: { label: 'Not checked', tone: 'neutral', help: 'This lead has not been processed yet.' },
}

export const EMAIL_STATUS = {
  valid_public: {
    label: 'Public + MX verified',
    tone: 'ok',
    help: 'Found published on the business\'s own website, and the domain accepts mail. Mailbox deliverability is still not guaranteed.',
  },
  mx_valid: { label: 'MX verified', tone: 'ok', help: 'The domain publishes MX records, so it can receive mail.' },
  domain_valid: { label: 'Domain resolves', tone: 'warn', help: 'The domain exists but publishes no MX record.' },
  syntax_valid: { label: 'Syntax only', tone: 'warn', help: 'The address parses correctly; DNS was not confirmed.' },
  risky: { label: 'Risky', tone: 'warn', help: 'Disposable domain, or an address that may not belong to this business.' },
  invalid: { label: 'Invalid', tone: 'danger', help: 'Syntax failed or the domain does not exist.' },
  unknown: { label: 'Unknown', tone: 'neutral', help: 'Validation could not be completed (for example a DNS timeout).' },
}

export const WEBSITE_STATUS = {
  valid: { label: 'Valid', tone: 'ok' },
  redirected: { label: 'Redirected', tone: 'warn' },
  unavailable: { label: 'Unavailable', tone: 'danger' },
  blocked: { label: 'Blocked', tone: 'warn' },
  mismatch: { label: 'Identity mismatch', tone: 'danger' },
  not_found: { label: 'Not found', tone: 'danger' },
  not_a_website: { label: 'Social/directory only', tone: 'warn' },
  no_website: { label: 'No website', tone: 'neutral' },
  not_checked: { label: 'Not checked', tone: 'neutral' },
}

export const PHONE_STATUS = {
  valid: { label: 'Valid', tone: 'ok' },
  possible: { label: 'Possible', tone: 'warn' },
  invalid: { label: 'Invalid', tone: 'danger' },
  unparseable: { label: 'Unparseable', tone: 'danger' },
  ambiguous_region: { label: 'No country code', tone: 'warn' },
  unavailable: { label: 'None', tone: 'neutral' },
}

export const CHANNEL = {
  whatsapp: { label: 'WhatsApp', tone: 'wa', emoji: '🟢' },
  email: { label: 'Email', tone: 'info', emoji: '🔵' },
  linkedin: { label: 'LinkedIn', tone: 'linkedin', emoji: '🟣' },
  phone: { label: 'Call', tone: 'warn', emoji: '🟠' },
  website_contact: { label: 'Contact form', tone: 'neutral', emoji: '⚪' },
  none: { label: 'Skipped', tone: 'neutral', emoji: '⚪' },
  '': { label: 'Not processed', tone: 'neutral', emoji: '⚪' },
}

export const LINKEDIN_STATUS = {
  found: { label: 'Company page found', tone: 'linkedin' },
  not_found: { label: 'Not found on site', tone: 'neutral' },
  not_checked: {
    label: 'Not checked',
    tone: 'neutral',
    help: 'Skipped because WhatsApp or email was already usable for this lead.',
  },
}

export const ITEM_STATUS = {
  pending: { label: 'Queued', tone: 'neutral' },
  running: { label: 'Running', tone: 'info' },
  completed: { label: 'Done', tone: 'ok' },
  failed: { label: 'Failed', tone: 'danger' },
  skipped: { label: 'Skipped', tone: 'neutral' },
}

export const AUDIT_STATUS = {
  completed: { label: 'Audited', tone: 'ok' },
  failed: { label: 'Audit failed', tone: 'danger' },
  no_clear_opportunity: { label: 'No clear opportunity', tone: 'neutral' },
  '': { label: '—', tone: 'neutral' },
}

// Per-check status (see backend scoring.STATUS_LABELS) - every catalogued
// check resolves to exactly one of these, never a fabricated pass/fail for
// something that was not actually measured.
export const CHECK_STATUS = {
  pass: { label: 'Passed', tone: 'ok' },
  warning: { label: 'Needs Improvement', tone: 'warn' },
  fail: { label: 'Critical', tone: 'danger' },
  not_verified: { label: 'Not Verified', tone: 'neutral' },
  not_applicable: { label: 'Not Applicable', tone: 'neutral' },
}

export const describe = (map, key, fallbackLabel) =>
  map[key] || { label: fallbackLabel || key || '—', tone: 'neutral' }

// Premium scorecard categories (see backend scoring.AUDIT_CATEGORY_LABELS).
export const AUDIT_CATEGORY_LABELS = {
  technical: 'Technical SEO',
  onpage: 'On-Page SEO',
  local_seo: 'Local SEO',
  offpage: 'Off-Page & Authority',
  performance: 'Performance',
  accessibility: 'Accessibility',
  security: 'Security',
  ux_conversion: 'UX & Conversion',
}

export function scoreTone(score) {
  if (score === null || score === undefined) return 'neutral'
  if (score >= 90) return 'danger'
  if (score >= 75) return 'danger'
  if (score >= 60) return 'warn'
  if (score >= 40) return 'info'
  return 'ok'
}

export const tierClass = (tier) =>
  ({ 'A+': 'tier-aplus', A: 'tier-a', B: 'tier-b', C: 'tier-c', D: 'tier-d' }[tier] || 'tier-d')

export function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text)
  // localhost over plain http still needs the fallback in some browsers.
  return new Promise((resolve, reject) => {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    try {
      document.execCommand('copy')
      resolve()
    } catch (e) {
      reject(e)
    } finally {
      document.body.removeChild(ta)
    }
  })
}
