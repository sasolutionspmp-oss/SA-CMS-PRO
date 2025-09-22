import React from 'react'
import PageHeader from '../components/patterns/PageHeader'
import StatCard from '../components/patterns/StatCard'
import DataGrid from '../components/ui/DataGrid'
import QuickActionCard from '../components/patterns/QuickActionCard'
import Timeline from '../components/patterns/Timeline'
import Card from '../components/patterns/Card'
import Button from '../components/ui/Button'
import Table from '../components/ui/Table'
import {
  FinanceIcon,
  GlobeIcon,
  PulseIcon,
  TrendUpIcon,
  UsersIcon,
} from '../components/icons'

const portfolio = [
  {
    id: 'west',
    segment: 'Western region programs',
    owner: 'Kim Porter',
    revenue: '$182M',
    margin: '16.8%',
    burn: 'On target',
  },
  {
    id: 'federal',
    segment: 'Federal infrastructure',
    owner: 'Jason King',
    revenue: '$146M',
    margin: '15.2%',
    burn: 'Watch labor',
  },
  {
    id: 'health',
    segment: 'Healthcare builds',
    owner: 'Nora Ibarra',
    revenue: '$128M',
    margin: '19.4%',
    burn: 'Ahead',
  },
  {
    id: 'industrial',
    segment: 'Industrial & logistics',
    owner: 'Chris Patel',
    revenue: '$203M',
    margin: '17.1%',
    burn: 'On target',
  },
]

const cashflow = [
  { id: 'july', cells: ['July', '$42.6M', '$38.2M', '$4.4M surplus'] },
  { id: 'aug', cells: ['August', '$45.1M', '$43.7M', '$1.4M surplus'] },
  { id: 'sep', cells: ['September', '$47.8M', '$50.1M', '$2.3M shortfall (plan)'] },
]

const financeEvents = [
  {
    id: 'draw',
    title: 'Capital draw approved · Innovation campus',
    description: '$18.4M released ahead of schedule after punch walk with owner CFO.',
    timestamp: 'Today · 10:20 MT',
    status: 'completed' as const,
  },
  {
    id: 'alert',
    title: 'Commodity hedge triggered',
    description: 'Steel futures executed · Estimated savings $1.1M across three programs.',
    timestamp: 'Yesterday · 14:45 MT',
    status: 'completed' as const,
  },
  {
    id: 'forecast',
    title: 'Backlog risk scenario review',
    description: 'Finance + delivery aligning on Q4 cash pacing adjustments.',
    timestamp: 'Mon · 16:25 MT',
    status: 'active' as const,
  },
]

export default function Finance() {
  return (
    <div className="space-y-12">
      <PageHeader
        title="Finance Command Center"
        subtitle="Equip executives with real-time financial clarity while aligning delivery, risk, and commercial strategy."
        breadcrumbs={['Command Suite', 'Finance']}
        actions={
          <>
            <Button variant="secondary" icon={<UsersIcon className="h-4 w-4" />}>
              Share CFO briefing
            </Button>
            <Button variant="primary" icon={<FinanceIcon className="h-4 w-4" />}>
              Launch forecast cycle
            </Button>
          </>
        }
        meta={
          <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 text-xs font-semibold">
            <GlobeIcon className="h-4 w-4" /> Portfolio currency hedged · FX exposure &lt; 2%
          </span>
        }
      />

      <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="booked revenue"
          value="$659M"
          helper="YTD captured across active programs"
          trend={{ direction: 'up', value: '+8.4%', label: 'vs. plan' }}
          icon={<FinanceIcon className="h-6 w-6" />}
        />
        <StatCard
          label="gross margin"
          value="17.2%"
          helper="Staying within tactical guardrails"
          trend={{ direction: 'up', value: '+1.1%', label: 'stability' }}
          icon={<TrendUpIcon className="h-6 w-6" />}
        />
        <StatCard
          label="cash flow status"
          value="Positive"
          helper="Rolling 90-day outlook remains surplus"
          trend={{ direction: 'up', value: '$3.7M', label: 'swing from Q1' }}
          icon={<PulseIcon className="h-6 w-6" />}
        />
        <StatCard
          label="strategic backlog"
          value="$1.9B"
          helper="Aligned with 14-month visibility and risk scoring"
          trend={{ direction: 'up', value: '+$120M', label: 'pipeline growth' }}
          icon={<GlobeIcon className="h-6 w-6" />}
        />
      </section>

      <Card className="space-y-6" padding="relaxed">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-text-primary">Portfolio performance</h2>
            <p className="text-sm text-text-secondary">Monitor revenue capture, margin posture, and burn alignment by strategic segment.</p>
          </div>
          <div className="flex items-center gap-3">
            <Button variant="outline" size="sm">
              Export executive deck
            </Button>
            <Button variant="primary" size="sm">
              Trigger variance review
            </Button>
          </div>
        </div>
        <DataGrid
          headers={['Segment', 'Owner', 'Revenue', 'Margin', 'Burn posture']}
          rows={portfolio.map((item) => ({
            id: item.id,
            cells: [
              <span className="font-semibold text-text-primary" key="segment">
                {item.segment}
              </span>,
              item.owner,
              item.revenue,
              item.margin,
              item.burn,
            ],
            searchText: `${item.segment} ${item.owner}`,
          }))}
          searchPlaceholder="Search segments"
        />
      </Card>

      <section className="grid gap-6 lg:grid-cols-[1.6fr,1fr]">
        <Card className="space-y-6" padding="relaxed">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold text-text-primary">Cash flow outlook</h2>
              <p className="text-sm text-text-secondary">Projected draw versus spend across rolling quarters.</p>
            </div>
            <Button variant="outline" size="sm">
              Open treasury view
            </Button>
          </div>
          <Table headers={['Month', 'Projected inflow', 'Projected outflow', 'Net']} rows={cashflow} />
        </Card>
        <QuickActionCard
          title="Forecast controls"
          description="Keep finance, delivery, and commercial stakeholders aligned around scenarios."
          icon={<TrendUpIcon className="h-6 w-6" />}
          actions={
            <div className="space-y-3 text-sm text-text-secondary">
              <p>• Quarterly scenario modeling with delivery sign-off</p>
              <p>• Margin guardrails with automated exception routing</p>
              <p>• Owner change impact planning &amp; capital reprioritization</p>
              <Button variant="secondary" size="sm" className="mt-2">
                Adjust forecast
              </Button>
            </div>
          }
        />
      </section>

      <Timeline title="Finance pulse" items={financeEvents} />
    </div>
  )
}
