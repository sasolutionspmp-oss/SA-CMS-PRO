import React from 'react'
import { NavLink } from 'react-router-dom'
import Button from './Button'
import {
  ComplianceIcon,
  EstimateIcon,
  FinanceIcon,
  HistoryIcon,
  IngestIcon,
  PMIcon,
  SafetyIcon,
  SearchIcon,
  SettingsIcon,
} from '../icons'
import { cn } from '../../lib/utils'

type NavProps = {
  isOpen: boolean
  onClose: () => void
  onNavigate?: () => void
}

const links = [
  { to: '/', label: 'Ingest', description: 'Intake orchestration', icon: IngestIcon },
  { to: '/search', label: 'Search', description: 'Knowledge discovery', icon: SearchIcon },
  { to: '/estimate', label: 'Estimate', description: 'Forecast and pricing', icon: EstimateIcon },
  { to: '/compliance', label: 'Compliance', description: 'Governance posture', icon: ComplianceIcon },
  { to: '/pm', label: 'Project Ops', description: 'Program milestones', icon: PMIcon },
  { to: '/safety', label: 'Safety', description: 'Field intelligence', icon: SafetyIcon },
  { to: '/finance', label: 'Finance', description: 'Cash & margin', icon: FinanceIcon },
  { to: '/settings', label: 'Settings', description: 'Access & controls', icon: SettingsIcon },
  { to: '/history', label: 'History', description: 'Audit trail', icon: HistoryIcon },
]

export default function Nav({ isOpen, onClose, onNavigate }: NavProps) {
  return (
    <>
      <div
        className={cn(
          'fixed inset-0 z-30 bg-brand-primary/40 backdrop-blur-sm transition-opacity duration-200 lg:hidden',
          isOpen ? 'opacity-100' : 'pointer-events-none opacity-0'
        )}
        onClick={onClose}
      />
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 flex w-72 flex-col overflow-hidden rounded-r-3xl bg-gradient-to-b from-brand-primary via-brand-secondary to-brand-primary text-white shadow-brand transition-transform duration-300 ease-out lg:static lg:translate-x-0 lg:shadow-none',
          isOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="flex flex-1 flex-col gap-8 overflow-y-auto px-6 py-8">
          <div className="space-y-6">
            <div className="flex items-center justify-between gap-4">
              <img src="/branding/logo-horizontal-light.svg" alt="S&A Solutions" className="w-48" />
              <button
                type="button"
                onClick={onClose}
                className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-white/10 text-white transition hover:bg-white/20 lg:hidden"
                aria-label="Close navigation"
              >
                ×
              </button>
            </div>
            <p className="text-sm text-brand-highlight/80">
              Tactical visibility into every project heartbeat with decisive, executive-ready clarity.
            </p>
          </div>
          <nav className="space-y-2">
            {links.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.to === '/'}
                onClick={() => {
                  onNavigate?.()
                  onClose()
                }}
                className={({ isActive }) =>
                  cn(
                    'group relative flex items-center gap-4 rounded-2xl px-4 py-3 text-sm font-semibold transition-colors',
                    isActive
                      ? 'bg-white/15 text-white shadow-lg shadow-brand/40'
                      : 'text-brand-highlight/80 hover:bg-white/10 hover:text-white'
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <span
                      className={cn(
                        'flex h-11 w-11 items-center justify-center rounded-2xl bg-white/10 text-brand-highlight transition-colors duration-200 group-hover:bg-white/20 group-hover:text-white',
                        isActive && 'bg-white text-brand-primary'
                      )}
                    >
                      <link.icon className="h-5 w-5" />
                    </span>
                    <span className="flex flex-1 flex-col">
                      <span>{link.label}</span>
                      <span className="text-xs font-normal text-brand-highlight/70 group-hover:text-white/80">{link.description}</span>
                    </span>
                    {isActive && (
                      <span className="absolute inset-y-2 right-2 w-1 rounded-full bg-white" aria-hidden />
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
          <div className="mt-auto space-y-4 rounded-3xl bg-white/10 p-5 text-sm text-white/80">
            <p className="font-semibold uppercase tracking-[0.24em] text-brand-highlight/80">Mission focus</p>
            <p>
              Empower regional teams with guided playbooks, real-time compliance checks, and unified financial optics.
            </p>
            <Button variant="ghost" size="sm" className="border-white/30 text-white hover:border-white/60">
              Share executive briefing
            </Button>
          </div>
        </div>
        <div className="px-6 pb-6">
          <div className="rounded-3xl border border-white/15 bg-white/10 p-5 text-sm text-white/80">
            <p className="font-semibold text-white">Summit Week</p>
            <p className="mt-1 text-xs text-brand-highlight/80">Denver HQ · July 18</p>
            <p className="mt-4 text-xs">
              Align division roadmaps with the Tactical Vision charter. Secure your seats by Monday for VIP lab walkthroughs.
            </p>
            <Button variant="ghost" size="sm" className="mt-4 border-white/30 text-white hover:border-white/60">
              Reserve briefing seats
            </Button>
          </div>
        </div>
      </aside>
    </>
  )
}
