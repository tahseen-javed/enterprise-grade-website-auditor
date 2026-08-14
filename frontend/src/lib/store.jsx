import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { api, eventStreamUrl } from './api'

const AppCtx = createContext(null)
export const useApp = () => useContext(AppCtx)

const MAX_LOG = 300

export function AppProvider({ children }) {
  const [theme, setThemeState] = useState(() => {
    try {
      return localStorage.getItem('oe-theme') || 'system'
    } catch {
      return 'system'
    }
  })
  const [toasts, setToasts] = useState([])
  const [connected, setConnected] = useState(false)
  const [log, setLog] = useState([])
  const [progress, setProgress] = useState({})
  const [runningJobs, setRunningJobs] = useState([])
  const [settings, setSettings] = useState(null)
  const [jobs, setJobs] = useState([])
  const [activeJobId, setActiveJobId] = useState(() => {
    try {
      const v = localStorage.getItem('oe-active-job')
      return v ? Number(v) : null
    } catch {
      return null
    }
  })
  const [jobPulse, setJobPulse] = useState(0)

  const toastId = useRef(0)

  // ---- theme ----
  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') delete root.dataset.theme
    else root.dataset.theme = theme
    try {
      localStorage.setItem('oe-theme', theme)
    } catch {}
  }, [theme])

  const setTheme = useCallback((t) => setThemeState(t), [])

  // ---- toasts ----
  const toast = useCallback((message, kind = 'ok') => {
    const id = ++toastId.current
    setToasts((prev) => [...prev, { id, message, kind }])
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4200)
  }, [])

  // ---- settings ----
  const refreshSettings = useCallback(async () => {
    try {
      const s = await api.settings()
      setSettings(s)
      return s
    } catch (err) {
      setSettings((prev) => prev ?? { error: err.message })
      return null
    }
  }, [])

  // ---- jobs ----
  const refreshJobs = useCallback(async () => {
    try {
      const { jobs: list } = await api.jobs(50)
      setJobs(list)
      setActiveJobId((current) => {
        if (current && list.some((j) => j.id === current)) return current
        const running = list.find((j) => j.is_running)
        return running ? running.id : list.length ? list[0].id : null
      })
      return list
    } catch {
      return []
    }
  }, [])

  useEffect(() => {
    refreshSettings()
    refreshJobs()
  }, [refreshSettings, refreshJobs])

  useEffect(() => {
    try {
      if (activeJobId) localStorage.setItem('oe-active-job', String(activeJobId))
      else localStorage.removeItem('oe-active-job')
    } catch {}
  }, [activeJobId])

  // ---- live event stream ----
  useEffect(() => {
    let source
    let retry
    let closed = false

    const connect = () => {
      source = new EventSource(eventStreamUrl())

      source.addEventListener('hello', (e) => {
        setConnected(true)
        try {
          const data = JSON.parse(e.data)
          if (Array.isArray(data.recent)) setLog(data.recent.slice(0, MAX_LOG))
          if (data.progress) setProgress(data.progress)
          if (data.running_jobs) setRunningJobs(data.running_jobs)
        } catch {}
      })

      source.addEventListener('activity', (e) => {
        try {
          const evt = JSON.parse(e.data)
          setLog((prev) => [evt, ...prev].slice(0, MAX_LOG))
        } catch {}
      })

      source.addEventListener('progress', (e) => {
        try {
          const evt = JSON.parse(e.data)
          if (evt.data && evt.data.job_id) {
            setProgress((prev) => ({ ...prev, [evt.data.job_id]: evt.data }))
          }
        } catch {}
      })

      source.addEventListener('job', (e) => {
        try {
          const evt = JSON.parse(e.data)
          const status = evt.data?.status
          if (status === 'running') {
            setRunningJobs((prev) => (prev.includes(evt.job_id) ? prev : [...prev, evt.job_id]))
          } else if (['completed', 'cancelled', 'failed'].includes(status)) {
            setRunningJobs((prev) => prev.filter((id) => id !== evt.job_id))
            setProgress((prev) => {
              const next = { ...prev }
              delete next[evt.job_id]
              return next
            })
            toast(
              status === 'completed'
                ? `Job ${evt.job_id} finished`
                : `Job ${evt.job_id} ${status}`,
              status === 'completed' ? 'ok' : 'err',
            )
          }
          setJobPulse((n) => n + 1)
        } catch {}
      })

      source.onerror = () => {
        setConnected(false)
        source.close()
        if (!closed) retry = setTimeout(connect, 3000)
      }
    }

    connect()
    return () => {
      closed = true
      clearTimeout(retry)
      source?.close()
    }
  }, [toast])

  // Job list follows the stream rather than polling on a timer.
  useEffect(() => {
    if (jobPulse === 0) return
    refreshJobs()
  }, [jobPulse, refreshJobs])

  const value = useMemo(
    () => ({
      theme, setTheme,
      toasts, toast,
      connected, log,
      progress, runningJobs,
      settings, refreshSettings,
      jobs, refreshJobs, activeJobId, setActiveJobId,
      profileConfigured: settings?.profile_status?.configured ?? true,
      missingProfileFields: settings?.profile_status?.missing_core ?? [],
    }),
    [
      theme, setTheme, toasts, toast, connected, log, progress, runningJobs,
      settings, refreshSettings, jobs, refreshJobs, activeJobId,
    ],
  )

  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>
}

// Small data-fetch hook with loading/error states so pages stay declarative.
export function useFetch(fn, deps = [], { skip = false } = {}) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(!skip)
  const [error, setError] = useState(null)
  const [tick, setTick] = useState(0)
  const fnRef = useRef(fn)
  fnRef.current = fn

  useEffect(() => {
    if (skip) {
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    fnRef
      .current()
      .then((res) => {
        if (!cancelled) {
          setData(res)
          setError(null)
        }
      })
      .catch((err) => {
        if (!cancelled && err.name !== 'AbortError') setError(err)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, skip])

  return { data, loading, error, reload: () => setTick((t) => t + 1), setData }
}
