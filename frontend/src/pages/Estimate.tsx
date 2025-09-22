import React from 'react'
import PageHeader from '../components/patterns/PageHeader'
import StatCard from '../components/patterns/StatCard'
import DataGrid from '../components/ui/DataGrid'
import Card from '../components/patterns/Card'
import Button from '../components/ui/Button'
import QuickActionCard from '../components/patterns/QuickActionCard'
import Table from '../components/ui/Table'
import {
  EstimateIcon,
  FinanceIcon,
  PulseIcon,
  TrendUpIcon,
  UsersIcon,
} from '../components/icons'

const estimates = [
  {
    id: 'metro-hub',
    project: 'Metro logistics hub · Phase II',
    stage: 'Executive review',
    lead: 'Jamal Turner',
    margin: '17.8%',
    probability: '72%',
  },
  {
    id: 'wind',
    project: 'High plains wind campus',
    stage: 'Pricing calibration',
    lead: 'Amelia Boyd',
    margin: '15.2%',
    probability: '64%',
  },
  {
    id: 'rail',
    project: 'Southwest rail spur upgrade',
    stage: 'Bid modeling',
    lead: 'Kailen Bishop',
    margin: '14.1%',
    probability: '58%',
  },
  {
    id: 'hospital',
    project: 'Regional care hospital expansion',
    stage: 'Client workshop',
    lead: 'Priya Desai',
    margin: '19.4%',
    probability: '81%',
  },
]

const costBreakdown = [
  {
    id: 'direct',
    cells: ['Direct labor', '$48.2M', 'Baseline +1.6%', 'Labor agreements updated'],
  },
  {
    id: 'materials',
    cells: ['Fabricated materials', '$32.7M', 'Bulk buy −3.1%', 'Supplier incentives locked'],
  },
  {
    id: 'equipment',
    cells: ['Equipment & fleet', '$9.6M', 'Rental mix −1.8%', 'Telematics optimization'],
  },
  {
    id: 'contingency',
    cells: ['Contingency', '$6.4M', 'Scenario 2', 'Weather/permit buffer maintained'],
  },
]

export default function Estimate() {
  return (
    <div className="space-y-12">
      <PageHeader
        title="Estimate Intelligence Studio"
        subtitle="Balance competitiveness and profitability using live market data, risk modeling, and playbook-backed guidance."
        breadcrumbs={['Command Suite', 'Commercials']}
        actions={
          <>
            <Button variant="secondary" icon={<UsersIcon className="h-4 w-4" />}>
              Share with ops
            </Button>
            <Button variant="primary" icon={<EstimateIcon className="h-4 w-4" />}>
              Launch scenario sprint
            </Button>
          </>
        }
        meta={
          <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 text-xs font-semibold">
            <TrendUpIcon className="h-4 w-4" /> Market indices synchronized · 6 suppliers updated
          </span>
        }
      />

      <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="active estimates"
          value="24"
          helper="Tracked across regions with shared benchmarks"
          trend={{ direction: 'up', value: '+4', label: 'pipeline growth' }}
          icon={<EstimateIcon className="h-6 w-6" />}
        />
        <StatCard
          label="weighted win rate"
          value="64%"
          helper="AI scoring calibrates probability with feedback loops"
          trend={{ direction: 'up', value: '+7%', label: 'vs. last quarter' }}
          icon={<PulseIcon className="h-6 w-6" />}
        />
        <StatCard
          label="target margin band"
          value="16.4%"
          helper="Aligned to executive guardrails with early risk mitigation"
          trend={{ direction: 'up', value: '+0.9%', label: 'stability' }}
          icon={<FinanceIcon className="h-6 w-6" />}
        />
        <StatCard
          label="value at risk"
          value="$12.6M"
          helper="Priority items flagged for strategic intervention"
          trend={{ direction: 'down', value: '−$1.2M', label: 'mitigated' }}
          icon={<TrendUpIcon className="h-6 w-6 rotate-180" />}
        />
      </section>

      <Card className="space-y-6" padding="relaxed">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-text-primary">Estimate pipeline</h2>
            <p className="text-sm text-text-secondary">Segmented view of pursuits, pricing alignment, and stakeholder readiness.</p>
          </div>
          <div className="flex items-center gap-3">
            <Button variant="outline" size="sm">
              Export pursuit pack
            </Button>
            <Button variant="primary" size="sm">
              Align kickoff
            </Button>
          </div>
        </div>
        <DataGrid
          headers={['Project', 'Stage', 'Lead estimator', 'Target margin', 'Win probability']}
          rows={estimates.map((estimate) => ({
            id: estimate.id,
            cells: [
              <span className="font-semibold text-text-primary" key="proj">
                {estimate.project}
              </span>,
              estimate.stage,
              estimate.lead,
              estimate.margin,
              <span key="prob" className="font-semibold text-brand-primary">
                {estimate.probability}
              </span>,
            ],
            searchText: `${estimate.project} ${estimate.stage} ${estimate.lead}`,
          }))}
          searchPlaceholder="Search by pursuit or stage"
        />
      </Card>

      <section className="grid gap-6 lg:grid-cols-[1.6fr,1fr]">
        <Card className="space-y-6" padding="relaxed">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold text-text-primary">Scenario modeling focus</h2>
              <p className="text-sm text-text-secondary">AI-driven adjustments to navigate commodity volatility and labor supply.</p>
            </div>
            <Button variant="outline" size="sm">
              View sensitivity model
            </Button>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-2xl bg-surface-muted/60 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">Scenario A · Accelerated award</p>
              <p className="mt-2 text-sm text-text-secondary">
                Pull forward procurement by 21 days to lock price holds and maintain labor continuity.
              </p>
            </div>
            <div className="rounded-2xl bg-surface-muted/60 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">Scenario B · Staggered delivery</p>
              <p className="mt-2 text-sm text-text-secondary">
                Shift steel packages into two drops. Cash flow improves by $1.1M while maintaining risk posture.
              </p>
            </div>
            <div className="rounded-2xl bg-surface-muted/60 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">Scenario C · Alternate supplier</p>
              <p className="mt-2 text-sm text-text-secondary">
                Activate pre-qualified supplier pool, balancing 2.8% cost increase with 14-day schedule resilience.
              </p>
            </div>
            <div className="rounded-2xl bg-surface-muted/60 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">Scenario D · Self-perform pivot</p>
              <p className="mt-2 text-sm text-text-secondary">
                Blend self-perform crews on critical path packages; margin improves 0.6% under controlled overtime.
              </p>
            </div>
          </div>
        </Card>
        <QuickActionCard
          title="Executive guardrails"
          description="Strategic directives enforced across every pursuit with automated alerts when assumptions drift."
          icon={<FinanceIcon className="h-6 w-6" />}
          actions={
            <div className="space-y-3 text-sm text-text-secondary">
              <p>• Minimum blended margin 15% · Auto-alert at 13.5%</p>
              <p>• Labor risk buffer maintained · Contract labor mix ≤ 22%</p>
              <p>• Cash-positive milestones by month six · Finance co-sign required</p>
              <Button variant="secondary" size="sm" className="mt-2">
                Adjust guardrails
              </Button>
            </div>
          }
        />
      </section>

      <Card className="space-y-6" padding="relaxed">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-text-primary">Cost architecture snapshot</h2>
            <p className="text-sm text-text-secondary">Aligns with live supply inputs and integrated production rates.</p>
          </div>
          <Button variant="outline" size="sm">
            Export cost sheet
          </Button>
        </div>
        <Table
          headers={['Cost group', 'Value', 'Variance', 'Notes']}
          rows={costBreakdown}
          compact
        />
      </Card>
    </div>
  )
}
