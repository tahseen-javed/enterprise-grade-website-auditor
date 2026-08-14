// Hand-rolled SVG charts: no charting dependency, theme-aware via CSS vars.

export function ScoreDial({ score, size = 128, label = 'opportunity', stroke = 11 }) {
  const has = score !== null && score !== undefined
  const pct = has ? Math.max(0, Math.min(100, score)) : 0
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const color = !has
    ? 'var(--ink-4)'
    : pct >= 75
      ? 'var(--danger)'
      : pct >= 60
        ? 'var(--warn)'
        : pct >= 40
          ? 'var(--brand)'
          : 'var(--ok)'

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
         aria-label={`${label} score ${has ? pct : 'not scored'}`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth={stroke} />
      {has && (
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke}
          strokeDasharray={`${(pct / 100) * c} ${c}`} strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: 'stroke-dasharray 600ms cubic-bezier(0.4,0,0.2,1)' }}
        />
      )}
      <text x="50%" y="47%" textAnchor="middle" dominantBaseline="middle"
            style={{ fontSize: size * 0.26, fontWeight: 700, fill: 'var(--ink)', letterSpacing: '-0.03em' }}>
        {has ? pct : '—'}
      </text>
      <text x="50%" y="66%" textAnchor="middle" dominantBaseline="middle"
            style={{ fontSize: size * 0.085, fill: 'var(--ink-3)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
        {label}
      </text>
    </svg>
  )
}

export function Donut({ data, size = 168, thickness = 26, centerLabel, centerValue }) {
  const items = (data || []).filter((d) => d.value > 0)
  const total = items.reduce((sum, d) => sum + d.value, 0)
  const r = (size - thickness) / 2
  const c = 2 * Math.PI * r

  if (!total) {
    return (
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth={thickness} />
        <text x="50%" y="50%" textAnchor="middle" dominantBaseline="middle"
              style={{ fontSize: 12, fill: 'var(--ink-4)' }}>
          No data
        </text>
      </svg>
    )
  }

  let offset = 0
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth={thickness} />
      {items.map((d, i) => {
        const len = (d.value / total) * c
        const el = (
          <circle
            key={i} cx={size / 2} cy={size / 2} r={r} fill="none" stroke={d.color}
            strokeWidth={thickness} strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-offset}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          >
            <title>{`${d.label}: ${d.value}`}</title>
          </circle>
        )
        offset += len
        return el
      })}
      {(centerValue !== undefined || centerLabel) && (
        <>
          <text x="50%" y="46%" textAnchor="middle" dominantBaseline="middle"
                style={{ fontSize: size * 0.2, fontWeight: 700, fill: 'var(--ink)', letterSpacing: '-0.03em' }}>
            {centerValue}
          </text>
          <text x="50%" y="63%" textAnchor="middle" dominantBaseline="middle"
                style={{ fontSize: size * 0.075, fill: 'var(--ink-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            {centerLabel}
          </text>
        </>
      )}
    </svg>
  )
}

export function Legend({ data, onSelect }) {
  const total = (data || []).reduce((s, d) => s + d.value, 0)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 7, minWidth: 0 }}>
      {(data || []).map((d, i) => (
        <div
          key={i}
          className="row"
          style={{ gap: 8, cursor: onSelect ? 'pointer' : 'default' }}
          onClick={() => onSelect?.(d)}
        >
          <span className="dot" style={{ background: d.color }} />
          <span className="small" style={{ color: 'var(--ink-2)' }}>{d.label}</span>
          <div className="spacer" />
          <span className="small tabular strong">{d.value}</span>
          <span className="xsmall muted tabular" style={{ width: 40, textAlign: 'right' }}>
            {total ? `${Math.round((d.value / total) * 100)}%` : '0%'}
          </span>
        </div>
      ))}
    </div>
  )
}

export function BarList({ data, max, formatValue }) {
  const items = data || []
  const peak = max || Math.max(1, ...items.map((d) => d.value))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {items.map((d, i) => (
        <div key={i} className="meter-row">
          <span className="name truncate" title={d.label}>{d.label}</span>
          <span className="progress">
            <span
              className="bar"
              style={{
                width: `${(d.value / peak) * 100}%`,
                background: d.color || undefined,
              }}
            />
          </span>
          <span className="val">{formatValue ? formatValue(d.value) : d.value}</span>
        </div>
      ))}
    </div>
  )
}

export function Sparkline({ points, width = 130, height = 34, color = 'var(--brand)' }) {
  const vals = points || []
  if (vals.length < 2) return null
  const max = Math.max(...vals, 1)
  const min = Math.min(...vals, 0)
  const span = max - min || 1
  const step = width / (vals.length - 1)
  const d = vals
    .map((v, i) => `${i === 0 ? 'M' : 'L'} ${i * step} ${height - ((v - min) / span) * height}`)
    .join(' ')
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

// ---- premium audit scorecard (health-style: higher is always better) ----

export function healthBand(score) {
  if (score === null || score === undefined) return { key: 'unknown', label: 'Not measured' }
  if (score >= 85) return { key: 'green', label: 'Good' }
  if (score >= 70) return { key: 'yellow', label: 'Fair' }
  if (score >= 50) return { key: 'orange', label: 'Needs work' }
  return { key: 'red', label: 'Poor' }
}

export function BandPill({ score }) {
  const b = healthBand(score)
  return <span className={`band-pill ${b.key}`}>{b.label}</span>
}

export function CategoryScorecards({ categories }) {
  return (
    <div className="grid grid-4">
      {(categories || []).map((c) => {
        const b = healthBand(c.health)
        return (
          <div key={c.category} className="scorecard-tile">
            <div className="top">
              <span className="name">{c.label}</span>
              <BandPill score={c.health} />
            </div>
            <div className="score">
              {c.health}
              <span className="den">/100</span>
            </div>
            <div className="progress">
              <div className={`bar ${b.key === 'green' ? 'ok' : b.key === 'red' ? 'danger' : b.key}`} style={{ width: `${c.health}%` }} />
            </div>
            {c.why_it_matters && <p className="why">{c.why_it_matters}</p>}
          </div>
        )
      })}
    </div>
  )
}

export function SeverityBreakdown({ critical = 0, high = 0, warnings = 0, passed = 0 }) {
  const data = [
    { label: 'Critical', value: critical, color: 'var(--danger)' },
    { label: 'High priority', value: high, color: 'var(--warn)' },
    { label: 'Warning', value: warnings, color: 'var(--yellow)' },
    { label: 'Passed', value: passed, color: 'var(--ok)' },
  ]
  const total = critical + high + warnings + passed
  return (
    <div className="row row-wrap" style={{ gap: 'var(--sp-6)', alignItems: 'center' }}>
      <Donut data={data} centerValue={total} centerLabel="checks" />
      <Legend data={data} />
    </div>
  )
}

export const CHART_COLORS = {
  whatsapp: '#128c7e',
  email: '#2b6cb0',
  linkedin: '#6b3fa0',
  phone: '#b3730c',
  website_contact: '#7048b6',
  none: '#94a0b5',
  'A+': '#c53434',
  A: '#b3730c',
  B: '#3b5bdb',
  C: '#2b6cb0',
  D: '#94a0b5',
}
