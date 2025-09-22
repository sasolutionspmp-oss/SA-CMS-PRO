import React, { useState } from 'react'
import PageHeader from '../components/patterns/PageHeader'
import StatCard from '../components/patterns/StatCard'
import QuickActionCard from '../components/patterns/QuickActionCard'
import Timeline from '../components/patterns/Timeline'
import Card from '../components/patterns/Card'
import Button from '../components/ui/Button'
import SearchBar from '../components/ui/SearchBar'
import {
  DocumentIcon,
  PulseIcon,
  SearchIcon,
  ShieldCheckIcon,
  SparkIcon,
  UsersIcon,
} from '../components/icons'

const savedLenses = ['Executive Briefs', 'Preconstruction Benchmarks', 'Risk Mitigation', 'Safety Intel', 'Cost Trends', 'Lessons Learned']

const investigations = [
  {
    id: 'inv-1',
    title: 'Modular hospital · RFP alignment',
    description: 'Highlighted historical bids within ±3% variance and surfaced 7 compliance caveats.',
    timestamp: 'Today · 08:45 MT',
    status: 'completed' as const,
  },
  {
    id: 'inv-2',
    title: 'Concrete supplier · Disruption scenario',
    description: 'Scenario planning flagged 2 alternative vendors with existing onboarding and above-target safety scores.',
    timestamp: 'Yesterday · 16:12 MT',
    status: 'completed' as const,
  },
  {
    id: 'inv-3',
    title: 'Regulatory change · Environmental updates',
    description: 'Machine reading of Colorado HB-224 adds 5 automated checks to compliance library.',
    timestamp: 'Mon · 11:08 MT',
    status: 'active' as const,
  },
]

export default function Search() {
  const [query, setQuery] = useState('')

  const highlightedResults = [
    {
      title: 'Prefabricated mechanical wing · Cost benchmarks',
      category: 'Estimate insights',
      excerpt: 'Updated Q2 numbers reflect a 2.3% savings opportunity using modular assembly sequence 4.',
    },
    {
      title: 'Safety observation cluster · Denver International',
      category: 'Safety intel',
      excerpt: 'AI clustering surfaced repeat incidents tied to subcontractor onboarding. Recommended playbook triggered.',
    },
    {
      title: 'Compliance: Federal Buy America requirements',
      category: 'Compliance',
      excerpt: 'Automated crosswalk shows 16 active projects affected. All supplier documentation current as of yesterday.',
    },
  ].filter((result) => result.title.toLowerCase().includes(query.toLowerCase()) || query.length === 0)

  return (
    <div className="space-y-12">
      <PageHeader
        title="Intelligence Search Studio"
        subtitle="Search across ingested knowledge, financials, field reports, and compliance obligations with AI that speaks your operation."
        breadcrumbs={['Command Suite', 'Discovery']}
        actions={
          <>
            <Button variant="secondary" icon={<SparkIcon className="h-4 w-4" />}>
              Save smart lens
            </Button>
            <Button variant="primary" icon={<SearchIcon className="h-4 w-4" />}>
              Launch guided search
            </Button>
          </>
        }
        meta={
          <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 text-xs font-semibold">
            <ShieldCheckIcon className="h-4 w-4" /> All enterprise sources validated · 4 minutes ago
          </span>
        }
      />

      <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="indexed intelligence"
          value="4.8M"
          helper="Documents, RFIs, change orders, and knowledge assets"
          trend={{ direction: 'up', value: '+6.2%', label: 'last 30 days' }}
          icon={<DocumentIcon className="h-6 w-6" />}
        />
        <StatCard
          label="median response time"
          value="1.4s"
          helper="Elastic pipelines answer on enterprise-grade infrastructure"
          trend={{ direction: 'down', value: '−0.6s', label: 'performance lift' }}
          icon={<PulseIcon className="h-6 w-6" />}
        />
        <StatCard
          label="ai assisted briefs"
          value="312"
          helper="Delivered this week to business development and ops"
          trend={{ direction: 'up', value: '+58', label: 'week over week' }}
          icon={<SparkIcon className="h-6 w-6" />}
        />
        <StatCard
          label="confidence index"
          value="94%"
          helper="Benchmark vs. expert validation across critical insights"
          trend={{ direction: 'up', value: '+3%', label: 'quality assurance' }}
          icon={<ShieldCheckIcon className="h-6 w-6" />}
        />
      </section>

      <Card className="space-y-8" padding="relaxed">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-text-primary">Unified search</h2>
            <p className="text-sm text-text-secondary">Cross-cut budgets, compliance, safety, and production narratives instantly.</p>
          </div>
          <div className="flex items-center gap-3">
            <Button variant="outline" size="sm">
              View search analytics
            </Button>
            <Button variant="primary" size="sm">
              Share investigation
            </Button>
          </div>
        </div>
        <SearchBar onSearch={setQuery} placeholder="Search by project, risk, vendor, or narrative..." />
        <div className="grid gap-4 md:grid-cols-3">
          {highlightedResults.map((result) => (
            <div key={result.title} className="space-y-3 rounded-2xl border border-brand-primary/10 bg-surface-muted/60 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">{result.category}</p>
              <h3 className="text-base font-semibold text-text-primary">{result.title}</h3>
              <p className="text-sm text-text-secondary">{result.excerpt}</p>
              <Button variant="outline" size="sm" className="mt-2">
                View intelligence
              </Button>
            </div>
          ))}
          {highlightedResults.length === 0 && (
            <div className="rounded-2xl border border-dashed border-brand-primary/20 bg-white/40 p-6 text-sm text-text-secondary md:col-span-3">
              Tailor your query to surface multi-domain insights, or activate an AI research sprint.
            </div>
          )}
        </div>
      </Card>

      <section className="grid gap-6 lg:grid-cols-[1.6fr,1fr]">
        <QuickActionCard
          title="Saved lenses"
          description="Curated, AI-maintained perspectives that stay synchronized with every ingestion cycle."
          icon={<SearchIcon className="h-6 w-6" />}
          actions={
            <div className="flex flex-wrap gap-2">
              {savedLenses.map((lens) => (
                <span key={lens} className="inline-flex items-center rounded-full border border-brand-primary/15 bg-white/20 px-3 py-1 text-xs font-semibold text-brand-primary/90">
                  {lens}
                </span>
              ))}
              <Button variant="secondary" size="sm" className="mt-2">
                Create new lens
              </Button>
            </div>
          }
        />
        <Card className="space-y-6" padding="relaxed">
          <h2 className="text-lg font-semibold text-text-primary">Signal amplifiers</h2>
          <div className="space-y-4 text-sm text-text-secondary">
            <div className="flex items-start gap-3 rounded-2xl bg-surface-muted/60 p-4">
              <UsersIcon className="mt-1 h-5 w-5 text-brand-accent" />
              <div>
                <p className="font-semibold text-text-primary">Relationship graph boost</p>
                <p>Blend CRM, estimating, and field data to reveal influence networks guiding approvals.</p>
              </div>
            </div>
            <div className="flex items-start gap-3 rounded-2xl bg-surface-muted/60 p-4">
              <ShieldCheckIcon className="mt-1 h-5 w-5 text-brand-accent" />
              <div>
                <p className="font-semibold text-text-primary">Compliance overlay</p>
                <p>Apply regulatory filters that auto-update when new statutes or owner requirements drop.</p>
              </div>
            </div>
            <div className="flex items-start gap-3 rounded-2xl bg-surface-muted/60 p-4">
              <SparkIcon className="mt-1 h-5 w-5 text-brand-accent" />
              <div>
                <p className="font-semibold text-text-primary">Narrative generator</p>
                <p>Transform findings into executive-ready summaries with one-click distribution.</p>
              </div>
            </div>
          </div>
        </Card>
      </section>

      <Timeline title="Recent investigations" items={investigations} />
    </div>
  )
}
