import React from 'react'
import PageHeader from '../components/patterns/PageHeader'
import StatCard from '../components/patterns/StatCard'
import DataGrid from '../components/ui/DataGrid'
import QuickActionCard from '../components/patterns/QuickActionCard'
import Timeline from '../components/patterns/Timeline'
import Card from '../components/patterns/Card'
import Button from '../components/ui/Button'
import {
  AlertIcon,
  DocumentIcon,
  GlobeIcon,
  ShieldCheckIcon,
  UsersIcon,
} from '../components/icons'

const obligations = [
  {
    id: 'osha',
    program: 'OSHA 300 reporting',
    owner: 'Morgan Ellis',
    region: 'National',
    status: 'Ready',
    due: 'Aug 1',
    statusTone: 'positive' as const,
  },
  {
    id: 'epa',
    program: 'EPA stormwater permit',
    owner: 'Ravi Patel',
    region: 'Colorado',
    status: 'Pending docs',
    due: 'Jul 22',
    statusTone: 'warning' as const,
  },
  {
    id: 'buy-america',
    program: 'Buy America compliance',
    owner: 'Lena Brooks',
    region: 'Federal',
    status: 'Escalated',
    due: 'Jul 15',
    statusTone: 'danger' as const,
  },
  {
    id: 'state',
    program: 'State wage reporting',
    owner: 'Luis Romero',
    region: 'Utah',
    status: 'In review',
    due: 'Aug 8',
    statusTone: 'warning' as const,
  },
]

const timelineItems = [
  {
    id: 'audit',
    title: 'Denver International · Compliance audit',
    description: 'Field audit complete with zero recordables; digital binder sent to owner portal.',
    timestamp: 'Today · 11:30 MT',
    status: 'completed' as const,
  },
  {
    id: 'policy',
    title: 'Updated silica exposure policy published',
    description: 'All crews acknowledged in app. Safety analytics adjusting leading indicator thresholds.',
    timestamp: 'Yesterday · 15:20 MT',
    status: 'completed' as const,
  },
  {
    id: 'notice',
    title: 'DOT notice: highway lane closure guidance',
    description: 'Transportation team reviewing to ensure weekend work remains compliant.',
    timestamp: 'Mon · 09:05 MT',
    status: 'active' as const,
  },
]

export default function Compliance() {
  return (
    <div className="space-y-12">
      <PageHeader
        title="Compliance Command Hub"
        subtitle="Maintain bulletproof documentation, stay ahead of regulatory shifts, and automate sign-offs across every program."
        breadcrumbs={['Command Suite', 'Risk & Compliance']}
        actions={
          <>
            <Button variant="secondary" icon={<UsersIcon className="h-4 w-4" />}>
              Notify legal
            </Button>
            <Button variant="primary" icon={<ShieldCheckIcon className="h-4 w-4" />}>
              Launch compliance sweep
            </Button>
          </>
        }
        meta={
          <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 text-xs font-semibold">
            <GlobeIcon className="h-4 w-4" /> Monitoring 43 jurisdictions · zero overdue obligations
          </span>
        }
      />

      <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="compliance score"
          value="97.6"
          helper="Weighted across safety, labor, environmental, and contractual"
          trend={{ direction: 'up', value: '+1.4', label: 'last 30 days' }}
          icon={<ShieldCheckIcon className="h-6 w-6" />}
        />
        <StatCard
          label="audits completed"
          value="18"
          helper="Strategic audits delivered year-to-date"
          trend={{ direction: 'up', value: '+3', label: 'vs. plan' }}
          icon={<DocumentIcon className="h-6 w-6" />}
        />
        <StatCard
          label="policies current"
          value="122"
          helper="Live across operations with workforce acknowledgement"
          trend={{ direction: 'up', value: '+8', label: 'last release' }}
          icon={<GlobeIcon className="h-6 w-6" />}
        />
        <StatCard
          label="open corrective actions"
          value="4"
          helper="All tied to training refresh scheduled this week"
          trend={{ direction: 'down', value: '−6', label: 'closing fast' }}
          icon={<AlertIcon className="h-6 w-6" />}
        />
      </section>

      <Card className="space-y-6" padding="relaxed">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-text-primary">Regulatory obligations</h2>
            <p className="text-sm text-text-secondary">Centralized view of requirements, ownership, and due dates with automated workflows.</p>
          </div>
          <div className="flex items-center gap-3">
            <Button variant="outline" size="sm">
              Export compliance register
            </Button>
            <Button variant="primary" size="sm">
              Request evidence
            </Button>
          </div>
        </div>
        <DataGrid
          headers={['Program', 'Owner', 'Region', 'Status', 'Due']}
          rows={obligations.map((obligation) => ({
            id: obligation.id,
            cells: [
              <span className="font-semibold text-text-primary" key="program">
                {obligation.program}
              </span>,
              obligation.owner,
              obligation.region,
              <span
                key="status"
                className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${
                  obligation.statusTone === 'positive'
                    ? 'bg-success/15 text-success'
                    : obligation.statusTone === 'warning'
                    ? 'bg-warning/15 text-warning'
                    : 'bg-danger/15 text-danger'
                }`}
              >
                {obligation.status}
              </span>,
              obligation.due,
            ],
            searchText: `${obligation.program} ${obligation.owner} ${obligation.region}`,
          }))}
          searchPlaceholder="Search obligations"
        />
      </Card>

      <section className="grid gap-6 lg:grid-cols-[1.6fr,1fr]">
        <Card className="space-y-6" padding="relaxed">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold text-text-primary">Regulatory intelligence brief</h2>
              <p className="text-sm text-text-secondary">AI-curated updates mapped to impacted projects and contractual clauses.</p>
            </div>
            <Button variant="outline" size="sm">
              Share digest
            </Button>
          </div>
          <div className="space-y-4 text-sm text-text-secondary">
            <div className="rounded-2xl bg-surface-muted/60 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">Federal</p>
              <p className="mt-1 text-text-primary">Infrastructure Investment & Jobs Act reporting updates published.</p>
              <p className="mt-2">Affected: 6 active civil projects · Finance & PM notified.</p>
            </div>
            <div className="rounded-2xl bg-surface-muted/60 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">State</p>
              <p className="mt-1 text-text-primary">Colorado Senate Bill 88 adds climate disclosure requirements.</p>
              <p className="mt-2">Compliance playbook refreshed · Sustainability leads briefed.</p>
            </div>
            <div className="rounded-2xl bg-surface-muted/60 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">Local</p>
              <p className="mt-1 text-text-primary">Denver city ordinance updates after-hours work guidance.</p>
              <p className="mt-2">PMO notified · Auto-updated in scheduling guardrails.</p>
            </div>
          </div>
        </Card>
        <QuickActionCard
          title="Assurance toolkit"
          description="Keep audit playbooks at your fingertips with automated evidence pulls and approvals."
          icon={<DocumentIcon className="h-6 w-6" />}
          actions={
            <div className="space-y-3 text-sm text-text-secondary">
              <p>• Field binder automation · Photo & signature capture</p>
              <p>• Digital attestations for subcontractor onboarding</p>
              <p>• Owner-specific workflows with scheduled reminders</p>
              <Button variant="secondary" size="sm" className="mt-2">
                Launch assurance flow
              </Button>
            </div>
          }
        />
      </section>

      <Timeline title="Recent compliance milestones" items={timelineItems} />
    </div>
  )
}
