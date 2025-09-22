import React from 'react'
import Card from './Card'
import { cn } from '../../lib/utils'

type TimelineStatus = 'completed' | 'active' | 'upcoming'

type TimelineItem = {
  id: string
  title: string
  description: string
  timestamp: string
  status?: TimelineStatus
  meta?: React.ReactNode
}

type TimelineProps = {
  title: string
  items: TimelineItem[]
  className?: string
}

export default function Timeline({ title, items, className }: TimelineProps) {
  return (
    <Card className={cn('flex h-full flex-col gap-6', className)}>
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-text-primary">{title}</h3>
      </div>
      <ol className="relative ml-2 flex flex-col gap-6 border-l border-brand-primary/10 pl-6">
        {items.map((item) => (
          <li key={item.id} className="relative">
            <span
              className={cn(
                'absolute -left-[37px] flex h-8 w-8 items-center justify-center rounded-full border-2 border-surface-base bg-white text-sm font-semibold shadow-subtle',
                item.status === 'completed' && 'border-brand-accent text-brand-accent',
                item.status === 'active' && 'border-brand-highlight text-brand-primary',
                item.status === 'upcoming' && 'border-brand-primary/10 text-text-tertiary'
              )}
            >
              {item.status === 'completed' ? '✓' : item.status === 'active' ? '•' : '○'}
            </span>
            <div className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-semibold text-text-primary">{item.title}</p>
                <span className="text-xs font-medium uppercase tracking-wide text-text-tertiary">{item.timestamp}</span>
              </div>
              <p className="text-sm text-text-secondary">{item.description}</p>
              {item.meta && <div className="text-xs text-text-tertiary">{item.meta}</div>}
            </div>
          </li>
        ))}
      </ol>
    </Card>
  )
}
