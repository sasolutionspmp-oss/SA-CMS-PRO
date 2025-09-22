import React from 'react'
import PageHeader from '../components/patterns/PageHeader'
import StatCard from '../components/patterns/StatCard'
import DataGrid from '../components/ui/DataGrid'
import Card from '../components/patterns/Card'
import Button from '../components/ui/Button'
import QuickActionCard from '../components/patterns/QuickActionCard'
import Timeline from '../components/patterns/Timeline'
import {
  DocumentIcon,
  GlobeIcon,
  HistoryIcon,
  ShieldCheckIcon,
} from '../components/icons'

const auditLog = [
  {
    id: 'log-1',
    actor: 'Tactical Admin',
    action: 'Updated finance guardrails',
    scope: 'Portfolio',
    timestamp: 'Today · 08:58 MT',
  },
  {
    id: 'log-2',
    actor: 'Compliance Engine',
    action: 'Generated EPA stormwater evidence package',
    scope: 'Compliance',
    timestamp: 'Yesterday · 21:14 MT',
  },
  {
    id: 'log-3',
    actor: 'Safety Ops',
    action: 'Triggered zero-harm stand-down',
    scope: 'Field ops',
    timestamp: 'Yesterday · 06:42 MT',
  },
  {
    id: 'log-4',
    actor: 'System',
    action: 'Rotated API keys for integrations',
    scope: 'Security',
    timestamp: 'Mon · 02:10 MT',
  },
]

const timelineItems = [
  {
    id: 'export',
    title: 'Executive audit export delivered',
    description: 'Full audit trail sent to CFO office with compliance attachments.',
    timestamp: 'Today · 12:05 MT',
    status: 'completed' as const,
  },
  {
    id: 'retention',
    title: 'Retention policy review',
    description: 'Data governance confirmed 7-year retention for federal programs.',
    timestamp: 'Yesterday · 10:30 MT',
    status: 'completed' as const,
  },
  {
    id: 'insight',
    title: 'Historical insight surfaced',
    description: 'AI flagged recurring change-order pattern for rail projects.',
    timestamp: 'Mon · 16:00 MT',
    status: 'active' as const,
  },
]

export default function History() {
  return (
    <div className="space-y-12">
      <PageHeader
        title="History & Audit Archive"
        subtitle="Command-level visibility across every action, policy, and integration within the S&A Solutions platform."
        breadcrumbs={['Command Suite', 'History']}
        actions={
          <>
            <Button variant="secondary" icon={<DocumentIcon className="h-4 w-4" />}>
              Download latest export
            </Button>
            <Button variant="primary" icon={<ShieldCheckIcon className="h-4 w-4" />}>
              Launch audit report
            </Button>
          </>
        }
        meta={
          <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 text-xs font-semibold">
            <HistoryIcon className="h-4 w-4" /> Immutable ledger operational · Retention 7 years
          </span>
        }
      />

      <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="events captured"
          value="2.4M"
          helper="Granular records across modules"
          trend={{ direction: 'up', value: '+11%', label: 'year over year' }}
          icon={<HistoryIcon className="h-6 w-6" />}
        />
        <StatCard
          label="critical changes"
          value="184"
          helper="Flagged for executive review"
          trend={{ direction: 'down', value: '−12%', label: 'stabilized' }}
          icon={<ShieldCheckIcon className="h-6 w-6" />}
        />
        <StatCard
          label="exports delivered"
          value="52"
          helper="Sent to executives and regulators"
          trend={{ direction: 'up', value: '+7', label: 'this quarter' }}
          icon={<DocumentIcon className="h-6 w-6" />}
        />
        <StatCard
          label="global regions"
          value="9"
          helper="Capturing unified audit data"
          trend={{ direction: 'up', value: '+2', label: 'expanded' }}
          icon={<GlobeIcon className="h-6 w-6" />}
        />
      </section>

      <Card className="space-y-6" padding="relaxed">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-text-primary">Live audit feed</h2>
            <p className="text-sm text-text-secondary">Immutable ledger of key activities, approvals, and automated actions.</p>
          </div>
          <div className="flex items-center gap-3">
            <Button variant="outline" size="sm">
              Export filtered log
            </Button>
            <Button variant="primary" size="sm">
              Schedule delivery
            </Button>
          </div>
        </div>
        <DataGrid
          headers={['Actor', 'Action', 'Scope', 'Timestamp']}
          rows={auditLog.map((entry) => ({
            id: entry.id,
            cells: [
              <span className="font-semibold text-text-primary" key="actor">
                {entry.actor}
              </span>,
              entry.action,
              entry.scope,
              entry.timestamp,
            ],
            searchText: `${entry.actor} ${entry.action} ${entry.scope}`,
          }))}
          searchPlaceholder="Search audit events"
        />
      </Card>

      <QuickActionCard
        title="Archive controls"
        description="Configure retention, encryption, and access policies for historical data."
        icon={<ShieldCheckIcon className="h-6 w-6" />}
        actions={
          <div className="space-y-3 text-sm text-text-secondary">
            <p>• Retention windows by jurisdiction and contract type</p>
            <p>• Legal hold activation with chain-of-custody tracking</p>
            <p>• Immutable storage snapshots with redundancy insights</p>
            <Button variant="secondary" size="sm" className="mt-2">
              Adjust archive settings
            </Button>
          </div>
        }
      />

      <Timeline title="History insights" items={timelineItems} />
    </div>
  )
}
