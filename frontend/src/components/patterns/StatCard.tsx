import React from 'react'
import Card from './Card'
import { cn } from '../../lib/utils'
import { TrendDownIcon, TrendUpIcon } from '../icons'

type TrendDirection = 'up' | 'down' | 'neutral'

type StatCardProps = {
  label: string
  value: string
  helper?: string
  trend?: {
    direction: TrendDirection
    value: string
    label?: string
  }
  icon?: React.ReactNode
  className?: string
}

export default function StatCard({ label, value, helper, trend, icon, className }: StatCardProps) {
  return (
    <Card className={cn('h-full', className)} padding="normal">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-4">
          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-text-tertiary">{label}</p>
          <p className="font-display text-3xl text-text-primary sm:text-4xl">{value}</p>
          {helper && <p className="text-sm text-text-secondary">{helper}</p>}
        </div>
        {icon && <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-accent/10 text-brand-accent">{icon}</div>}
      </div>
      {trend && (
        <div className="mt-6 inline-flex items-center gap-2 rounded-full bg-brand-highlight/20 px-4 py-2 text-xs font-semibold text-brand-secondary">
          {trend.direction === 'up' && <TrendUpIcon className="h-4 w-4" />}
          {trend.direction === 'down' && <TrendDownIcon className="h-4 w-4" />}
          {trend.direction === 'neutral' && <span className="h-2 w-2 rounded-full bg-brand-accent/60" />}
          <span>{trend.value}</span>
          {trend.label && <span className="text-text-tertiary">{trend.label}</span>}
        </div>
      )}
    </Card>
  )
}
