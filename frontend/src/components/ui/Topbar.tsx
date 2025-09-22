import React from 'react'
import Button from './Button'
import {
  BellIcon,
  GlobeIcon,
  MenuIcon,
  SparkIcon,
  UploadIcon,
  UsersIcon,
} from '../icons'

type TopbarProps = {
  onMenuClick?: () => void
}

const highlights = [
  { label: 'Global uptime', value: '99.97%', icon: GlobeIcon },
  { label: 'Active collaborators', value: '248', icon: UsersIcon },
]

export default function Topbar({ onMenuClick }: TopbarProps) {
  return (
    <header className="sticky top-0 z-30 border-b border-brand-primary/10 bg-white/80 backdrop-blur-xl">
      <div className="flex items-center justify-between gap-4 px-4 py-4 md:px-8">
        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={onMenuClick}
            className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-brand-primary/10 bg-surface-muted/60 text-brand-primary shadow-subtle transition-colors hover:border-brand-accent hover:text-brand-accent lg:hidden"
            aria-label="Toggle navigation"
          >
            <MenuIcon className="h-5 w-5" />
          </button>
          <div className="flex items-center gap-3">
            <img src="/branding/logo-mark.svg" alt="S&A Solutions globe emblem" className="h-12 w-12" />
            <div className="space-y-1">
              <p className="text-xs font-semibold uppercase tracking-[0.32em] text-text-tertiary">S&amp;A Solutions</p>
              <p className="text-lg font-semibold text-text-primary md:text-xl">Command Management Suite</p>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="secondary"
            size="sm"
            icon={<SparkIcon className="h-4 w-4" />}
            className="hidden sm:inline-flex"
          >
            Launch playbook
          </Button>
          <Button variant="primary" size="sm" icon={<UploadIcon className="h-4 w-4" />}>
            New initiative
          </Button>
          <button
            type="button"
            className="relative inline-flex h-11 w-11 items-center justify-center rounded-full border border-brand-primary/10 bg-surface-muted/60 text-brand-primary shadow-subtle transition hover:border-brand-accent hover:text-brand-accent"
            aria-label="Notifications"
          >
            <span className="absolute -right-0.5 -top-0.5 inline-flex h-3.5 w-3.5 items-center justify-center rounded-full bg-danger text-[10px] font-semibold text-white">
              4
            </span>
            <BellIcon className="h-5 w-5" />
          </button>
          <div className="hidden items-center gap-3 rounded-full border border-brand-primary/10 bg-surface-muted/60 px-3 py-1.5 pr-4 text-left shadow-subtle sm:flex">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-accent/20 font-semibold text-brand-primary">
              TA
            </div>
            <div className="leading-tight">
              <p className="text-xs font-semibold text-text-secondary">Tactical Admin</p>
              <p className="text-sm font-semibold text-text-primary">Operations</p>
            </div>
          </div>
        </div>
      </div>
      <div className="hidden items-center justify-between border-t border-brand-primary/10 px-4 py-3 text-xs text-text-secondary md:flex md:px-8">
        <div className="flex flex-wrap gap-6">
          {highlights.map((item) => (
            <div key={item.label} className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-accent/10 text-brand-accent">
                <item.icon className="h-4 w-4" />
              </div>
              <div className="leading-tight">
                <p className="text-[11px] uppercase tracking-[0.24em] text-text-tertiary">{item.label}</p>
                <p className="text-sm font-semibold text-text-primary">{item.value}</p>
              </div>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-3 rounded-full bg-brand-accent/10 px-3 py-1.5 text-brand-primary">
          <span className="text-[11px] font-semibold uppercase tracking-[0.28em]">Mission Alignment</span>
          <span className="rounded-full bg-white/90 px-3 py-1 text-xs font-bold text-brand-primary shadow-subtle">Level 04</span>
        </div>
      </div>
    </header>
  )
}
