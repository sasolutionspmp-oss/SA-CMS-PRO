import React from 'react'
import PageHeader from '../components/patterns/PageHeader'
import StatCard from '../components/patterns/StatCard'
import Card from '../components/patterns/Card'
import Button from '../components/ui/Button'
import QuickActionCard from '../components/patterns/QuickActionCard'
import Timeline from '../components/patterns/Timeline'
import {
  GlobeIcon,
  ShieldCheckIcon,
  UsersIcon,
  LayersIcon,
} from '../components/icons'

const timelineItems = [
  {
    id: 'role',
    title: 'Role update: Tactical Admin',
    description: 'Added Finance oversight scope and limited access for project-level adjustments.',
    timestamp: 'Today · 09:10 MT',
    status: 'completed' as const,
  },
  {
    id: 'integration',
    title: 'Integration sync · Viewpoint Vista',
    description: 'API keys rotated and validated. Data latency reduced to 2 minutes.',
    timestamp: 'Yesterday · 18:55 MT',
    status: 'completed' as const,
  },
  {
    id: 'policy',
    title: 'Security policy refresh published',
    description: 'Mandatory SSO & MFA enforcement across tactical workforce.',
    timestamp: 'Mon · 08:20 MT',
    status: 'completed' as const,
  },
]

const integrations = [
  { name: 'Procore', status: 'Live', detail: 'Field operations' },
  { name: 'Viewpoint Vista', status: 'Live', detail: 'Finance + payroll' },
  { name: 'ArcGIS', status: 'Live', detail: 'Geospatial intelligence' },
  { name: 'Bluebeam', status: 'Pilot', detail: 'Design coordination' },
]

export default function Settings() {
  return (
    <div className="space-y-12">
      <PageHeader
        title="Platform Configuration"
        subtitle="Govern access, integrations, and security posture across the S&A Solutions command platform."
        breadcrumbs={['Command Suite', 'Settings']}
        actions={
          <>
            <Button variant="secondary" icon={<UsersIcon className="h-4 w-4" />}>
              Invite admin
            </Button>
            <Button variant="primary" icon={<ShieldCheckIcon className="h-4 w-4" />}>
              Export policy packet
            </Button>
          </>
        }
        meta={
          <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 text-xs font-semibold">
            <GlobeIcon className="h-4 w-4" /> Global SSO enforced · 100% MFA coverage
          </span>
        }
      />

      <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="active users"
          value="1,842"
          helper="S&A Solutions staff + partner ecosystem"
          trend={{ direction: 'up', value: '+116', label: 'last quarter' }}
          icon={<UsersIcon className="h-6 w-6" />}
        />
        <StatCard
          label="integrations"
          value="14"
          helper="Enterprise systems synchronized"
          trend={{ direction: 'up', value: '+3', label: 'this year' }}
          icon={<LayersIcon className="h-6 w-6" />}
        />
        <StatCard
          label="mfa compliance"
          value="100%"
          helper="Mandatory for all tactical roles"
          trend={{ direction: 'up', value: '+8%', label: 'since enforcement' }}
          icon={<ShieldCheckIcon className="h-6 w-6" />}
        />
        <StatCard
          label="regions connected"
          value="9"
          helper="Aligned to growth roadmap"
          trend={{ direction: 'up', value: '+2', label: 'new this year' }}
          icon={<GlobeIcon className="h-6 w-6" />}
        />
      </section>

      <section className="grid gap-6 lg:grid-cols-[1.5fr,1fr]">
        <Card className="space-y-6" padding="relaxed">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold text-text-primary">Organization profile</h2>
              <p className="text-sm text-text-secondary">Update platform identity, branding, and enterprise contact routing.</p>
            </div>
            <Button variant="outline" size="sm">
              Edit profile
            </Button>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-2xl bg-surface-muted/60 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">Brand system</p>
              <p className="mt-2 text-sm text-text-secondary">Logos, typography, and palette synchronized across web and executive reporting.</p>
            </div>
            <div className="rounded-2xl bg-surface-muted/60 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">Notification routing</p>
              <p className="mt-2 text-sm text-text-secondary">Escalation map for owners, legal, finance, and field operations.</p>
            </div>
            <div className="rounded-2xl bg-surface-muted/60 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">Compliance artifacts</p>
              <p className="mt-2 text-sm text-text-secondary">Centralized evidence for SOC2, ISO27001, and customer audits.</p>
            </div>
            <div className="rounded-2xl bg-surface-muted/60 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-tertiary">Service catalog</p>
              <p className="mt-2 text-sm text-text-secondary">Manage access to ingestion, analytics, finance, and field safety modules.</p>
            </div>
          </div>
        </Card>
        <QuickActionCard
          title="Security posture"
          description="Continuous monitoring of credentials, device trust, and privileged actions."
          icon={<ShieldCheckIcon className="h-6 w-6" />}
          actions={
            <div className="space-y-3 text-sm text-text-secondary">
              <p>• Automated credential rotation with anomaly detection</p>
              <p>• Device trust scoring with geofenced approvals</p>
              <p>• Privileged activity playback for rapid audits</p>
              <Button variant="secondary" size="sm" className="mt-2">
                View security center
              </Button>
            </div>
          }
        />
      </section>

      <Card className="space-y-6" padding="relaxed">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-text-primary">Integrations</h2>
            <p className="text-sm text-text-secondary">Manage enterprise systems powering ingestion, analytics, and delivery.</p>
          </div>
          <Button variant="outline" size="sm">
            Add integration
          </Button>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {integrations.map((integration) => (
            <div key={integration.name} className="rounded-2xl border border-brand-primary/10 bg-surface-muted/60 p-4">
              <div className="flex items-center justify-between">
                <h3 className="text-base font-semibold text-text-primary">{integration.name}</h3>
                <span className="rounded-full bg-brand-accent/15 px-3 py-1 text-xs font-semibold text-brand-accent">
                  {integration.status}
                </span>
              </div>
              <p className="mt-2 text-sm text-text-secondary">{integration.detail}</p>
            </div>
          ))}
        </div>
      </Card>

      <Timeline title="Configuration activity" items={timelineItems} />
    </div>
  )
}
