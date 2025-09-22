import React from 'react'
import { cn } from '../../lib/utils'

type CardTone = 'default' | 'accent' | 'muted'

type CardProps = {
  children: React.ReactNode
  className?: string
  tone?: CardTone
  padding?: 'tight' | 'normal' | 'relaxed'
}

export default function Card({
  children,
  className,
  tone = 'default',
  padding = 'normal',
}: CardProps) {
  const toneClass: Record<CardTone, string> = {
    default:
      'bg-surface-elevated/95 border border-brand-primary/6 text-text-primary shadow-subtle backdrop-blur-md',
    accent:
      'bg-gradient-to-br from-brand-secondary via-brand-primary to-brand-primary text-white shadow-brand border border-white/15',
    muted: 'bg-surface-muted/80 border border-brand-primary/10 text-text-primary',
  }

  const paddingClass: Record<typeof padding, string> = {
    tight: 'p-4 sm:p-5',
    normal: 'p-6 sm:p-7',
    relaxed: 'p-8 sm:p-10',
  }

  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-3xl transition-shadow duration-300 hover:shadow-brand/60',
        toneClass[tone],
        paddingClass[padding],
        className
      )}
    >
      <div className="pointer-events-none absolute inset-0 bg-brand-diagonal" aria-hidden />
      <div className="relative z-10">{children}</div>
    </div>
  )
}
