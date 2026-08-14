// Single place that knows how to reach the backend.
// In dev, Vite proxies /api. In a build, VITE_API_BASE_URL points at it.
// Nothing here is hardcoded to a host.

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || ''
export const API_BASE = RAW_BASE.replace(/\/+$/, '')

export const apiUrl = (path) => `${API_BASE}/api${path}`

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function request(path, { method = 'GET', body, signal, raw = false } = {}) {
  const options = { method, signal, headers: {} }

  if (body instanceof FormData) {
    options.body = body
  } else if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json'
    options.body = JSON.stringify(body)
  }

  let response
  try {
    response = await fetch(apiUrl(path), options)
  } catch (err) {
    if (err.name === 'AbortError') throw err
    throw new ApiError(
      'Could not reach the backend. Check that it is running (start.bat) and try again.',
      0,
      String(err),
    )
  }

  if (raw) return response

  const isJson = (response.headers.get('content-type') || '').includes('application/json')
  const payload = isJson ? await response.json().catch(() => null) : await response.text()

  if (!response.ok) {
    const detail =
      (payload && (payload.detail || payload.message)) ||
      (typeof payload === 'string' ? payload.slice(0, 300) : '') ||
      `Request failed with HTTP ${response.status}`
    throw new ApiError(typeof detail === 'string' ? detail : JSON.stringify(detail), response.status, payload)
  }
  return payload
}

const qs = (params = {}) => {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') search.append(k, v)
  })
  const s = search.toString()
  return s ? `?${s}` : ''
}

export const api = {
  health: () => request('/health'),
  systemHealth: () => request('/system/health'),

  settings: () => request('/settings'),
  saveProfile: (patch) => request('/settings/profile', { method: 'PUT', body: patch }),
  saveEngine: (patch) => request('/settings/engine', { method: 'PUT', body: patch }),
  saveScoring: (patch) => request('/settings/scoring', { method: 'PUT', body: patch }),

  upload: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request('/uploads', { method: 'POST', body: fd })
  },
  uploadPreview: (id, sample) => request(`/uploads/${id}/preview${qs({ sample })}`),

  quickAudit: (url, name) =>
    request('/audits/quick', { method: 'POST', body: { url, name: name || undefined } }),

  createJob: (payload) => request('/jobs', { method: 'POST', body: payload }),
  jobs: (limit) => request(`/jobs${qs({ limit })}`),
  job: (id) => request(`/jobs/${id}`),
  jobProgress: (id) => request(`/jobs/${id}/progress`),
  jobStats: (id) => request(`/jobs/${id}/stats`),
  jobErrors: (id, limit) => request(`/jobs/${id}/errors${qs({ limit })}`),
  startJob: (id) => request(`/jobs/${id}/start`, { method: 'POST' }),
  pauseJob: (id) => request(`/jobs/${id}/pause`, { method: 'POST' }),
  resumeJob: (id) => request(`/jobs/${id}/resume`, { method: 'POST' }),
  cancelJob: (id) => request(`/jobs/${id}/cancel`, { method: 'POST' }),
  retryFailed: (id) => request(`/jobs/${id}/retry-failed`, { method: 'POST' }),
  deleteJob: (id) => request(`/jobs/${id}`, { method: 'DELETE' }),

  stats: (jobId) => request(`/stats${qs({ job_id: jobId })}`),
  recentEvents: (jobId, limit) => request(`/events/recent${qs({ job_id: jobId, limit })}`),

  leads: (params) => request(`/leads${qs(params)}`),
  lead: (id) => request(`/leads/${id}`),
  regenerateOutreach: (id) => request(`/leads/${id}/regenerate-outreach`, { method: 'POST' }),
  markSent: (id, draftId, sent) =>
    request(`/leads/${id}/mark-sent`, { method: 'POST', body: { draft_id: draftId, sent } }),

  exportColumns: () => request('/exports/columns'),
  exportHistory: () => request('/exports/history'),
}

export const downloadUrl = {
  csv: (jobId) => apiUrl(`/exports/${jobId}/csv`),
  xlsx: (jobId) => apiUrl(`/exports/${jobId}/xlsx`),
  reports: (jobId) => apiUrl(`/exports/${jobId}/reports.zip`),
  report: (leadId) => apiUrl(`/leads/${leadId}/report`),
}

export const eventStreamUrl = () => apiUrl('/events/stream')
