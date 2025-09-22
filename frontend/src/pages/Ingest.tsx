import React from 'react'
import PageHeader from '../components/patterns/PageHeader'
import StatCard from '../components/patterns/StatCard'
import QuickActionCard from '../components/patterns/QuickActionCard'
import Timeline from '../components/patterns/Timeline'
import DataGrid from '../components/ui/DataGrid'
import Button from '../components/ui/Button'
import Card from '../components/patterns/Card'
import {
  LayersIcon,
  PulseIcon,
  ShieldCheckIcon,
  UploadIcon,
  UsersIcon,
  ClockIcon,
} from '../components/icons'
import { cn } from '../lib/utils'

const pipelines = [
  {
    id: 'west',
    name: 'Bid intake · Western division',
    owner: 'Hannah Wright',
    lastRun: '09:42 MT',
    status: 'On track',
    sla: '02h 15m',
    statusTone: 'positive' as const,
  },
  {
    id: 'prefab',
    name: 'Prefab drawings sync',
    owner: 'Jun Kim',
    lastRun: '08:05 MT',
    status: 'Validating docs',
    sla: '03h 20m',
    statusTone: 'warning' as const,
  },
  {
    id: 'field',
    name: 'Field reports capture',
    owner: 'Sasha Ortiz',
    lastRun: '07:56 MT',
    status: 'Signal drop · retrying',
    sla: '01h 10m',
    statusTone: 'danger' as const,
  },
  {
    id: 'safety',
    name: 'Safety observations import',
    owner: 'Maurice Chen',
    lastRun: '06:32 MT',
    status: 'Complete',
    sla: '45m',
    statusTone: 'positive' as const,
  },
]

const logItems = [
  {
    id: '1',
    title: 'West region intake completed',
    description: '2,140 records normalized, 12 enrichment rules executed, no conflicts detected.',
    timestamp: '09:42 MT',
    status: 'completed' as const,
  },
  {
    id: '2',
    title: 'Prefab pipeline validation window',
    description: 'Auto-QA triggered 4 geometry checks for detailing packages awaiting approval.',
    timestamp: '08:12 MT',
    status: 'active' as const,
  },
  {
    id: '3',
    title: 'Field reports signal disruption',
    description: 'Cellular failover engaged, awaiting confirmation from Denver South tower partner.',
    timestamp: '07:56 MT',
    status: 'upcoming' as const,
  },
  {
    id: '4',
    title: 'Safety observations archive push',
    description: 'Nightly archive replicated to compliance vault. Restore point established.',
    timestamp: '02:13 MT',
    status: 'completed' as const,
  },
]

const connectors = ['Procore', 'Viewpoint Vista', 'ArcGIS', 'Bluebeam', 'PowerBI', 'Autodesk Build']

export default function Ingest() {
  return (
    <div className="space-y-12">
      <PageHeader
        title="Data Ingestion Command Center"
        subtitle="Orchestrate every feed, enforce quality, and deploy enriched insights to downstream teams without compromise."
        breadcrumbs={['Command Suite', 'Operational Intelligence']}
        actions={
          <>
            <Button variant="secondary" icon={<UsersIcon className="h-4 w-4" />}>
              Invite collaborator
            </Button>
            <Button variant="primary" icon={<UploadIcon className="h-4 w-4" />}>
              Launch manual ingest
            </Button>
          </>
        }
        meta={
          <>
            <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 text-xs font-semibold">
              <PulseIcon className="h-4 w-4" /> Pipeline heartbeat nominal
            </span>
            <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 text-xs font-semibold">
              <ClockIcon className="h-4 w-4" /> Next SLA check-in · 17 min
            </span>
          </>
        }
      />

      <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="records in queue"
          value="18,204"
          helper="Processed across 12 synchronized pipelines"
          trend={{ direction: 'up', value: '+12.4%', label: 'vs. last shift' }}
          icon={<LayersIcon className="h-6 w-6" />}
        />
        <StatCard
          label="median processing time"
          value="4m 18s"
          helper="Smart validation removed 92 minutes of manual review"
          trend={{ direction: 'down', value: '−18%', label: 'cycle gain' }}
          icon={<ClockIcon className="h-6 w-6" />}
        />
        <StatCard
          label="automation playbooks"
          value="27"
          helper="Five new playbooks ready for launch"
          trend={{ direction: 'up', value: '3 new', label: 'this week' }}
          icon={<PulseIcon className="h-6 w-6" />}
        />
        <StatCard
          label="data health index"
          value="98.4%"
          helper="Zero blocker anomalies detected across active feeds"
          trend={{ direction: 'up', value: '+1.2%', label: 'stability' }}
          icon={<ShieldCheckIcon className="h-6 w-6" />}
        />
      </section>

      <section className="grid gap-6 xl:grid-cols-[2fr,1fr]">
        <Card className="space-y-6" padding="relaxed">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold text-text-primary">Active pipelines</h2>
              <p className="text-sm text-text-secondary">Live telemetry and SLA adherence across ingestion sources.</p>
            </div>
            <div className="flex items-center gap-3">
              <Button variant="outline" size="sm">
                Export health report
              </Button>
              <Button variant="primary" size="sm">
                Schedule downtime
              </Button>
            </div>
          </div>
          <DataGrid
            headers={['Pipeline', 'Owner', 'Last run', 'Status', 'SLA window']}
            rows={pipelines.map((pipeline) => ({
              id: pipeline.id,
              cells: [
                <span className="font-semibold text-text-primary" key="name">
                  {pipeline.name}
                </span>,
                pipeline.owner,
                pipeline.lastRun,
                <span
                  key="status"
                  className={cn(
                    'inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold',
                    pipeline.statusTone === 'positive' && 'bg-success/15 text-success',
                    pipeline.statusTone === 'warning' && 'bg-warning/15 text-warning',
                    pipeline.statusTone === 'danger' && 'bg-danger/15 text-danger'
                  )}
                >
                  {pipeline.status}
                </span>,
                pipeline.sla,
              ],
              searchText: `${pipeline.name} ${pipeline.owner} ${pipeline.status}`,
            }))}
            searchPlaceholder="Search pipelines"
          />
        </Card>
        <QuickActionCard
          title="Connector readiness"
          description="All connectors tested for latency and compliance in the last 24 hours. Deploy new sources with a single approval."
          icon={<LayersIcon className="h-6 w-6" />}
          actions={
            <div className="flex flex-wrap gap-2">
              {connectors.map((connector) => (
                <span
                  key={connector}
                  className="inline-flex items-center rounded-full border border-brand-primary/15 bg-white/20 px-3 py-1 text-xs font-semibold text-brand-primary/90"
                >
                  {connector}
                </span>
              ))}
              <Button variant="secondary" size="sm" className="mt-2">
                Add connector
              </Button>
            </div>
          }
        />
      </section>

      <section className="grid gap-6 lg:grid-cols-[1.7fr,1fr]">
        <Card className="space-y-6" padding="relaxed">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold text-text-primary">Pipeline stabilization playbook</h2>
              <p className="text-sm text-text-secondary">Deploy guided responses when ingestion signals degrade.</p>
            </div>
            <Button variant="outline" size="sm">
              Download SOP
            </Button>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-3 rounded-2xl bg-surface-muted/70 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">Phase 01 · Detect</p>
              <p className="text-sm text-text-secondary">
                Automatic anomaly detection flags latency spikes and reroutes traffic before thresholds breach SLAs.
              </p>
            </div>
            <div className="space-y-3 rounded-2xl bg-surface-muted/70 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">Phase 02 · Respond</p>
              <p className="text-sm text-text-secondary">
                Launch guided workflows with escalation paths for vendor partners and field supervisors.
              </p>
            </div>
            <div className="space-y-3 rounded-2xl bg-surface-muted/70 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">Phase 03 · Validate</p>
              <p className="text-sm text-text-secondary">
                Run regression suites, then push validation receipts to compliance and finance archives automatically.
              </p>
            </div>
            <div className="space-y-3 rounded-2xl bg-surface-muted/70 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">Phase 04 · Optimize</p>
              <p className="text-sm text-text-secondary">
                Feed learnings back into AI-driven routing to tighten future ingest cycles by up to 28%.
              </p>
            </div>
          </div>
        </Card>
        <Timeline title="Live event log" items={logItems} />
      </section>
    </div>
  )
}
