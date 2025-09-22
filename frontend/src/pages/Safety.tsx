import React from 'react'
import PageHeader from '../components/patterns/PageHeader'
import StatCard from '../components/patterns/StatCard'
import DataGrid from '../components/ui/DataGrid'
import Timeline from '../components/patterns/Timeline'
import QuickActionCard from '../components/patterns/QuickActionCard'
import Card from '../components/patterns/Card'
import Button from '../components/ui/Button'
import {
  AlertIcon,
  CheckIcon,
  PulseIcon,
  ShieldCheckIcon,
  UsersIcon,
} from '../components/icons'

const observations = [
  {
    id: 'obs-1',
    project: 'Innovation campus build',
    lead: 'Jordan Fields',
    type: 'Proactive observation',
    status: 'Resolved',
    followUp: 'Coaching complete',
  },
  {
    id: 'obs-2',
    project: 'Terminal expansion',
    lead: 'Chris Long',
    type: 'Near miss',
    status: 'Open',
    followUp: 'Guardrail install today',
  },
  {
    id: 'obs-3',
    project: 'Distribution center automation',
    lead: 'Leah Romero',
    type: 'Toolbox talk insight',
    status: 'In review',
    followUp: 'Integrating into weekly standup',
  },
  {
    id: 'obs-4',
    project: 'Wind campus',
    lead: 'Hector Alvarez',
    type: 'Safety audit',
    status: 'Complete',
    followUp: 'Owner sign-off captured',
  },
]

const timelineItems = [
  {
    id: 'brief',
    title: 'Zero Harm briefing · Terminal expansion',
    description: 'Focus on logistics corridor and subcontractor onboarding. Attendance 98%.',
    timestamp: 'Today · 06:15 MT',
    status: 'completed' as const,
  },
  {
    id: 'weather',
    title: 'Weather alert · High plains wind campus',
    description: 'High wind plan activated. Lifts paused, crews reassigned to ground prep.',
    timestamp: 'Yesterday · 13:40 MT',
    status: 'active' as const,
  },
  {
    id: 'training',
    title: 'Mass notification drill completed',
    description: 'System uptime 100%. Response time improved by 12%.',
    timestamp: 'Mon · 15:30 MT',
    status: 'completed' as const,
  },
]

export default function Safety() {
  return (
    <div className="space-y-12">
      <PageHeader
        title="Safety Intelligence Console"
        subtitle="Drive proactive culture, track leading indicators, and deploy rapid interventions when risk emerges."
        breadcrumbs={['Command Suite', 'Field Ops']}
        actions={
          <>
            <Button variant="secondary" icon={<UsersIcon className="h-4 w-4" />}>
              Share crew insights
            </Button>
            <Button variant="primary" icon={<ShieldCheckIcon className="h-4 w-4" />}>
              Trigger safety stand down
            </Button>
          </>
        }
        meta={
          <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 text-xs font-semibold">
            <PulseIcon className="h-4 w-4" /> Leading indicators update · 5 minutes ago
          </span>
        }
      />

      <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="days incident-free"
          value="142"
          helper="Across enterprise projects"
          trend={{ direction: 'up', value: '+12', label: 'record streak' }}
          icon={<CheckIcon className="h-6 w-6" />}
        />
        <StatCard
          label="proactive observations"
          value="1,284"
          helper="Submissions in the last 30 days"
          trend={{ direction: 'up', value: '+9%', label: 'crew engagement' }}
          icon={<PulseIcon className="h-6 w-6" />}
        />
        <StatCard
          label="training completion"
          value="96%"
          helper="All-hands onboarding + specialized certifications"
          trend={{ direction: 'up', value: '+3%', label: 'month over month' }}
          icon={<ShieldCheckIcon className="h-6 w-6" />}
        />
        <StatCard
          label="risk hotspots"
          value="3"
          helper="All under mitigation playbook"
          trend={{ direction: 'down', value: '−2', label: 'since last review' }}
          icon={<AlertIcon className="h-6 w-6" />}
        />
      </section>

      <Card className="space-y-6" padding="relaxed">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-text-primary">Observation intelligence</h2>
            <p className="text-sm text-text-secondary">Unified log of leading indicators, curated for action with cross-team accountability.</p>
          </div>
          <div className="flex items-center gap-3">
            <Button variant="outline" size="sm">
              Export safety log
            </Button>
            <Button variant="primary" size="sm">
              Launch briefing
            </Button>
          </div>
        </div>
        <DataGrid
          headers={['Project', 'Lead', 'Type', 'Status', 'Follow-up']}
          rows={observations.map((observation) => ({
            id: observation.id,
            cells: [
              <span className="font-semibold text-text-primary" key="project">
                {observation.project}
              </span>,
              observation.lead,
              observation.type,
              observation.status,
              observation.followUp,
            ],
            searchText: `${observation.project} ${observation.lead} ${observation.type}`,
          }))}
          searchPlaceholder="Search observations"
        />
      </Card>

      <section className="grid gap-6 lg:grid-cols-[1.6fr,1fr]">
        <Card className="space-y-6" padding="relaxed">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold text-text-primary">Field readiness campaigns</h2>
              <p className="text-sm text-text-secondary">Targeted initiatives that reinforce Zero Harm culture across active programs.</p>
            </div>
            <Button variant="outline" size="sm">
              Schedule campaign
            </Button>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-2xl bg-surface-muted/60 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">Campaign · Shield</p>
              <p className="mt-2 text-sm text-text-secondary">Reinforce fall protection measures for all multi-story scopes.</p>
            </div>
            <div className="rounded-2xl bg-surface-muted/60 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">Campaign · Thrive</p>
              <p className="mt-2 text-sm text-text-secondary">Focus on wellness and fatigue awareness for extended summer shifts.</p>
            </div>
            <div className="rounded-2xl bg-surface-muted/60 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">Campaign · Catalyst</p>
              <p className="mt-2 text-sm text-text-secondary">Coach crew leads on coaching conversations for near-miss reporting.</p>
            </div>
            <div className="rounded-2xl bg-surface-muted/60 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">Campaign · Beacon</p>
              <p className="mt-2 text-sm text-text-secondary">Enhance night work readiness with lighting audits and logistics coordination.</p>
            </div>
          </div>
        </Card>
        <QuickActionCard
          title="Safety command actions"
          description="Deploy real-time interventions, messaging, and owner-ready reports."
          icon={<AlertIcon className="h-6 w-6" />}
          actions={
            <div className="space-y-3 text-sm text-text-secondary">
              <p>• Push targeted safety alerts with translation support</p>
              <p>• Activate stand-down workflow with instant attendance logs</p>
              <p>• Generate regulatory-ready incident packages automatically</p>
              <Button variant="secondary" size="sm" className="mt-2">
                Open command actions
              </Button>
            </div>
          }
        />
      </section>

      <Timeline title="Safety pulse" items={timelineItems} />
    </div>
  )
}
