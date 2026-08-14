import { useEffect, useState } from 'react'
import { copyText } from '../lib/format'
import { IconAlert, IconCheck, IconClose, IconCopy, IconInbox, IconInfo } from './icons'

export function Card({ children, className = '', ...rest }) {
  return (
    <div className={`card ${className}`} {...rest}>
      {children}
    </div>
  )
}

export function CardHead({ title, hint, children }) {
  return (
    <div className="card-head">
      <div style={{ minWidth: 0 }}>
        <h2>{title}</h2>
        {hint && <div className="hint">{hint}</div>}
      </div>
      <div className="spacer" />
      {children}
    </div>
  )
}

export function Stat({ label, value, meta, accent, icon, onClick, title }) {
  return (
    <div
      className={`stat${onClick ? ' clickable' : ''}`}
      style={accent ? { '--accent': accent } : undefined}
      onClick={onClick}
      title={title}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => (e.key === 'Enter' || e.key === ' ') && onClick() : undefined}
    >
      <div className="label">
        {icon}
        {label}
      </div>
      <div className={`value${String(value).length > 8 ? ' sm' : ''}`}>{value}</div>
      {meta && <div className="meta">{meta}</div>}
    </div>
  )
}

export function Badge({ tone = 'neutral', children, title, className = '' }) {
  return (
    <span className={`badge badge-${tone} ${className}`} title={title}>
      {children}
    </span>
  )
}

export function Progress({ value, tone, className = '' }) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0))
  return (
    <div className={`progress ${className}`}>
      <div className={`bar ${tone || ''}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

export function Alert({ tone = 'info', title, children, actions }) {
  const Icon = tone === 'danger' || tone === 'warn' ? IconAlert : IconInfo
  return (
    <div className={`alert alert-${tone}`}>
      <Icon size={16} />
      <div style={{ minWidth: 0, flex: 1 }}>
        {title && <strong>{title} </strong>}
        {children}
        {actions && <div className="row" style={{ marginTop: 10 }}>{actions}</div>}
      </div>
    </div>
  )
}

export function Empty({ icon, title, children, action }) {
  return (
    <div className="empty">
      <div className="icon">{icon || <IconInbox size={20} />}</div>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  )
}

export function Skeleton({ rows = 3 }) {
  return (
    <div style={{ padding: 'var(--sp-5)' }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton skeleton-line" />
      ))}
    </div>
  )
}

export function TableSkeleton({ rows = 6, cols = 5 }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <tbody>
          {Array.from({ length: rows }).map((_, r) => (
            <tr key={r}>
              {Array.from({ length: cols }).map((_, c) => (
                <td key={c}>
                  <div className="skeleton" style={{ height: 12, width: c === 0 ? '68%' : '46%' }} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ErrorState({ error, onRetry }) {
  return (
    <div className="empty">
      <div className="icon" style={{ background: 'var(--danger-soft)', color: 'var(--danger)' }}>
        <IconAlert size={20} />
      </div>
      <h3>Something went wrong</h3>
      <p>{error?.message || 'An unexpected error occurred.'}</p>
      {onRetry && (
        <button className="btn" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}

export function CopyButton({ text, label = 'Copy', small = true, block = false, onCopied }) {
  const [done, setDone] = useState(false)
  if (!text) return null
  return (
    <button
      className={`btn${small ? ' btn-sm' : ''}${block ? ' btn-block' : ''}`}
      onClick={async (e) => {
        e.stopPropagation()
        try {
          await copyText(text)
          setDone(true)
          onCopied?.()
          setTimeout(() => setDone(false), 1600)
        } catch {
          /* clipboard blocked; the text is still selectable on screen */
        }
      }}
    >
      {done ? <IconCheck size={13} /> : <IconCopy size={13} />}
      {done ? 'Copied' : label}
    </button>
  )
}

export function Field({ label, help, required, children, error }) {
  return (
    <div className="field">
      {label && (
        <label>
          {label}
          {required && <span className="req">*</span>}
        </label>
      )}
      {children}
      {error ? (
        <div className="help" style={{ color: 'var(--danger)' }}>
          {error}
        </div>
      ) : (
        help && <div className="help">{help}</div>
      )}
    </div>
  )
}

export function Switch({ checked, onChange, label, disabled }) {
  return (
    <label className="switch">
      <input
        type="checkbox"
        checked={!!checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="track" />
      {label && <span className="switch-label">{label}</span>}
    </label>
  )
}

export function Segmented({ value, onChange, options }) {
  return (
    <div className="seg">
      {options.map((o) => (
        <button
          key={o.value}
          className={value === o.value ? 'active' : ''}
          onClick={() => onChange(o.value)}
          type="button"
        >
          {o.label}
          {o.count !== undefined && ` (${o.count})`}
        </button>
      ))}
    </div>
  )
}

export function Modal({ open, onClose, title, children, footer, wide }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && onClose?.()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <>
      <div className="overlay" onClick={onClose} />
      <div className="modal" style={wide ? { width: 'min(880px, calc(100vw - 32px))' } : undefined} role="dialog" aria-modal="true">
        <div className="card-head">
          <h2>{title}</h2>
          <div className="spacer" />
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close">
            <IconClose size={16} />
          </button>
        </div>
        <div style={{ padding: 'var(--sp-5)', overflowY: 'auto' }}>{children}</div>
        {footer && <div className="card-foot row">{footer}</div>}
      </div>
    </>
  )
}

export function Drawer({ open, onClose, children, head }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && onClose?.()
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <>
      <div className="overlay" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true">
        <div className="drawer-head">
          <div style={{ minWidth: 0, flex: 1 }}>{head}</div>
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close">
            <IconClose size={16} />
          </button>
        </div>
        <div className="drawer-body">{children}</div>
      </aside>
    </>
  )
}

export function Pagination({ page, pages, total, onPage }) {
  if (pages <= 1) return null
  return (
    <div className="row" style={{ padding: 'var(--sp-3) var(--sp-5)' }}>
      <span className="small muted">
        Page {page} of {pages} · {total.toLocaleString()} leads
      </span>
      <div className="spacer" />
      <button className="btn btn-sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <button className="btn btn-sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </div>
  )
}

export function KV({ items }) {
  return (
    <div className="kv">
      {items
        .filter((i) => i)
        .map((item, i) => (
          <div key={i}>
            <div className="k">{item.k}</div>
            <div className="v">{item.v}</div>
          </div>
        ))}
    </div>
  )
}
