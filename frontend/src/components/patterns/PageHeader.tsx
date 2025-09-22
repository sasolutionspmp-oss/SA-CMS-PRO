import React from 'react'
import Card from './Card'
import { cn } from '../../lib/utils'

type PageHeaderProps = {
  title: string
  subtitle: string
  actions?: React.ReactNode
  breadcrumbs?: string[]
  meta?: React.ReactNode
  className?: string
}

export default function PageHeader({ title, subtitle, actions, breadcrumbs, meta, className }: PageHeaderProps) {
  return (
    <Card tone="accent" className={cn('overflow-hidden', className)} padding="relaxed">
      <div className="absolute inset-0 bg-brand-radial opacity-90" aria-hidden />
      <div className="relative z-10 flex flex-col gap-8 lg:flex-row lg:items-center lg:justify-between">
        <div className="space-y-6 text-white">
          {breadcrumbs && breadcrumbs.length > 0 && (
            <nav aria-label="Breadcrumb" className="text-xs uppercase tracking-[0.35em] text-brand-highlight/80">
              {breadcrumbs.join(' · ')}
            </nav>
          )}
          <div className="space-y-3">
            <h1 className="font-display text-3xl leading-tight sm:text-4xl">{title}</h1>
            <p className="max-w-3xl text-sm font-medium text-brand-highlight/90 sm:text-base">{subtitle}</p>
          </div>
          {meta && <div className="flex flex-wrap gap-3 text-xs text-brand-highlight/90">{meta}</div>}
        </div>
        {actions && (
          <div className="flex flex-col items-start gap-3 text-sm text-white sm:flex-row sm:items-center">
            {actions}
          </div>
        )}
      </div>
    </Card>
  )
}
