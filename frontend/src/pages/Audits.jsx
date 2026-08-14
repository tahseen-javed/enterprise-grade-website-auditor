import { useEffect, useState } from 'react'
import LeadDrawer from '../components/LeadDrawer'
import { ScoreDial } from '../components/charts'
import { JobPicker, LeadTable, NoJobYet, SearchBox } from '../components/shared'
import { Alert, Card, CardHead, Segmented, Stat } from '../components/ui'
import { api } from '../lib/api'
import { num } from '../lib/format'
import { useApp, useFetch } from '../lib/store'

const BANDS = [
  { value: '', label: 'All' },
  { value: '90', label: '90+' },
  { value: '75', label: '75+' },
  { value: '60', label: '60+' },
  { value: '40', label: '40+' },
]

export default function Audits() {
  const { activeJobId, jobs } = useApp()
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [band, setBand] = useState('')
  const [page, setPage] = useState(1)
  const [openId, setOpenId] = useState(null)

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 320)
    return () => clearTimeout(t)
  }, [search])
  useEffect(() => setPage(1), [debounced, band, activeJobId])

  const { data: stats } = useFetch(() => api.stats(activeJobId ?? undefined), [activeJobId])
  const { data, loading, error, reload } = useFetch(
    () =>
      api.leads({
        job_id: activeJobId ?? undefined,
        search: debounced || undefined,
        min_score: band || undefined,
        website_status: 'valid',
        sort: 'score_desc',
        page,
        page_size: 50,
      }),
    [activeJobId, debounced, band, page],
  )

  if (!jobs.length) return <div className="page"><Card><NoJobYet /></Card></div>

  const opp = stats?.opportunity_tiers || {}

  return (
    <div className="page stack">
      <Alert tone="info" title="How to read the score:">
        It measures <strong>how much room there is to improve</strong>, not how good the site is. A
        well-built site scores low. Every point traces back to a check that actually failed, and the
        breakdown is on each lead.
      </Alert>

      <div className="grid grid-4">
        <Stat label="Audited sites" value={num(stats?.processed)} accent="var(--brand)" />
        <Stat label="Very high (90+)" value={num(opp['Very High'])} accent="var(--danger)" />
        <Stat label="High (75–89)" value={num(opp.High)} accent="var(--warn)" />
        <Stat label="No clear opportunity" value={num(stats?.no_clear_opportunity)}
              meta="audited, nothing meaningful found" accent="var(--neutral)" />
      </div>

      <Card>
        <CardHead title="Audited websites" hint="Only sites whose identity was confirmed">
          <JobPicker compact />
        </CardHead>
        <div className="card-body row row-wrap">
          <SearchBox value={search} onChange={setSearch} />
          <Segmented value={band} onChange={setBand} options={BANDS} />
        </div>
        <LeadTable
          result={data}
          loading={loading}
          error={error}
          reload={reload}
          page={page}
          onPage={setPage}
          onOpen={setOpenId}
          columns={['score', 'website', 'problems', 'status']}
          emptyTitle="No audited websites match"
          emptyHint="Only businesses whose website was reachable and confirmed as theirs appear here."
        />
      </Card>

      <LeadDrawer leadId={openId} onClose={() => setOpenId(null)} onChanged={reload} />
    </div>
  )
}
