import React from 'react'
import PageHeader from '../components/patterns/PageHeader'
import StatCard from '../components/patterns/StatCard'
import DataGrid from '../components/ui/DataGrid'
import Timeline from '../components/patterns/Timeline'
import QuickActionCard from '../components/patterns/QuickActionCard'
import Card from '../components/patterns/Card'
import Button from '../components/ui/Button'
import Table from '../components/ui/Table'
import {
  ClockIcon,
  LayersIcon,
  PulseIcon,
  TrendUpIcon,
  UsersIcon,
} from '../components/icons'

const milestones = [
  {
    id: 'tower',
    name: 'Downtown tower fit-out',
    owner: 'Alex Hunter',
    phase: 'Interior build',
    status: 'On track',
    completion: '78%',
  },
  {
    id: 'terminal',
    name: 'International terminal expansion',
    owner: 'Charlotte Green',
    phase: 'Systems commissioning',
    status: 'Watching risk',
    completion: '64%',
  },
  {
    id: 'distribution',
    name: 'Distribution center automation',
    owner: 'Marcus Allen',
    phase: 'Mechanical install',
    status: 'Recovering',
    completion: '53%',
  },
  {
    id: 'innovation',
    name: 'Innovation campus build',
    owner: 'Sophie Torres',
    phase: 'Envelope & glazing',
    status: 'Ahead',
    completion: '88%',
  },
]

const sprintBurndown = [
  { id: 's1', cells: ['Sprint 21', 'Field onboarding', 'Completed', '11 tasks', '0 blockers'] },
  { id: 's2', cells: ['Sprint 22', 'MEP coordination', 'In progress', '8 of 12 tasks', '1 risk'] },
  { id: 's3', cells: ['Sprint 23', 'Digital twins sync', 'Planned', '14 tasks', 'ETA 7/25'] },
]

const events = [
  {
    id: 'coord',
    title: 'Critical path coordination · Terminal expansion',
    description: 'Night shift re-sequencing trimmed 4 days from baggage handling install.',
    timestamp: 'Today · 05:40 MT',
    status: 'completed' as const,
  },
  {
    id: 'qa',
    title: 'Quality audit · Innovation campus glazing',
    description: 'No deviations. Owner rep noted accelerated punch readiness.',
    timestamp: 'Yesterday · 17:15 MT',
    status: 'completed' as const,
  },
  {
    id: 'risk',
    title: 'Weather watch · High plains wind campus',
    description: 'Wind models trending above threshold. Safety to confirm weekend adjustments.',
    timestamp: 'Sun · 13:05 MT',
    status: 'active' as const,
  },
]

export default function PM() {
  return (
    <div className="space-y-12">
      <PageHeader
        title="Project Operations Control"
        subtitle="Track schedule certainty, resource alignment, and mission-critical milestones with executive clarity."
        breadcrumbs={['Command Suite', 'Delivery']}
        actions={
          <>
            <Button variant="secondary" icon={<UsersIcon className="h-4 w-4" />}>
              Share with owner rep
            </Button>
            <Button variant="primary" icon={<TrendUpIcon className="h-4 w-4" />}>
              Launch recovery sprint
            </Button>
          </>
        }
        meta={
          <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 text-xs font-semibold">
            <ClockIcon className="h-4 w-4" /> Average float across programs · 6.5 days
          </span>
        }
      />

      <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="programs on track"
          value="21"
          helper="Out of 24 active capital initiatives"
          trend={{ direction: 'up', value: '+3', label: 'stabilized' }}
          icon={<LayersIcon className="h-6 w-6" />}
        />
        <StatCard
          label="sprints completed"
          value="192"
          helper="Agile delivery cadences across the portfolio"
          trend={{ direction: 'up', value: '+11', label: 'since last review' }}
          icon={<PulseIcon className="h-6 w-6" />}
        />
        <StatCard
          label="resource utilization"
          value="87%"
          helper="Optimized to maintain coverage and surge capacity"
          trend={{ direction: 'down', value: '−4%', label: 'balancing load' }}
          icon={<UsersIcon className="h-6 w-6" />}
        />
        <StatCard
          label="critical path alerts"
          value="5"
          helper="Automations watching weekend work and dependencies"
          trend={{ direction: 'down', value: '−2', label: 'risk reduced' }}
          icon={<ClockIcon className="h-6 w-6" />}
        />
      </section>

      <Card className="space-y-6" padding="relaxed">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-text-primary">Program milestones</h2>
            <p className="text-sm text-text-secondary">Cross-program view with heat-sensing for risks, ahead-of-plan gains, and owner touchpoints.</p>
          </div>
          <div className="flex items-center gap-3">
            <Button variant="outline" size="sm">
              Export status deck
            </Button>
            <Button variant="primary" size="sm">
              Publish weekly brief
            </Button>
          </div>
        </div>
        <DataGrid
          headers={['Program', 'Lead', 'Phase', 'Status', 'Completion']}
          rows={milestones.map((milestone) => ({
            id: milestone.id,
            cells: [
              <span className="font-semibold text-text-primary" key="name">
                {milestone.name}
              </span>,
              milestone.owner,
              milestone.phase,
              milestone.status,
              milestone.completion,
            ],
            searchText: `${milestone.name} ${milestone.phase} ${milestone.owner}`,
          }))}
          searchPlaceholder="Search programs"
        />
      </Card>

      <section className="grid gap-6 lg:grid-cols-[1.6fr,1fr]">
        <Card className="space-y-6" padding="relaxed">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold text-text-primary">Agile sprint feed</h2>
              <p className="text-sm text-text-secondary">Coordinated sequences for engineering, field operations, and digital threads.</p>
            </div>
            <Button variant="outline" size="sm">
              View backlog
            </Button>
          </div>
          <Table headers={['Sprint', 'Focus', 'Status', 'Progress', 'Notes']} rows={sprintBurndown} compact />
        </Card>
        <QuickActionCard
          title="Delivery playbooks"
          description="Activate orchestrated responses for risk, owner change, or acceleration requests."
          icon={<LayersIcon className="h-6 w-6" />}
          actions={
            <div className="space-y-3 text-sm text-text-secondary">
              <p>• Weekend surge kit · Staffing, logistics, and cost guardrails</p>
              <p>• Owner change order handshake · Finance + PM alignment</p>
              <p>• Acceleration blueprint · Prefab, overtime, and QA adjustments</p>
              <Button variant="secondary" size="sm" className="mt-2">
                Launch playbook
              </Button>
            </div>
          }
        />
      </section>

      <Timeline title="Operations pulse" items={events} />
    </div>
  )
}
