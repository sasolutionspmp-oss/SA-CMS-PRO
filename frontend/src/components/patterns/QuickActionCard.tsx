import React from 'react'
import Card from './Card'
import { cn } from '../../lib/utils'

type QuickActionCardProps = {
  title: string
  description: string
  icon?: React.ReactNode
  actions?: React.ReactNode
  className?: string
}

export default function QuickActionCard({ title, description, icon, actions, className }: QuickActionCardProps) {
  return (
    <Card className={cn('flex h-full flex-col gap-6', className)}>
      <div className="flex items-start gap-4">
        {icon && <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-accent/10 text-brand-accent">{icon}</div>}
        <div className="space-y-2">
          <h3 className="text-lg font-semibold text-text-primary">{title}</h3>
          <p className="text-sm text-text-secondary">{description}</p>
        </div>
      </div>
      {actions && <div className="flex flex-wrap gap-3">{actions}</div>}
    </Card>
  )
}
