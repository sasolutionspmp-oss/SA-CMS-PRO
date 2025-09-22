import React from 'react'
import Card from '../patterns/Card'

type Props = { message: string; tone?: 'info' | 'success' | 'warning' | 'danger' }

const toneStyles: Record<Required<Props>['tone'], string> = {
  info: 'bg-brand-accent text-white',
  success: 'bg-success text-white',
  warning: 'bg-warning text-brand-primary',
  danger: 'bg-danger text-white',
}

export default function Toast({ message, tone = 'info' }: Props) {
  return (
    <div className="fixed bottom-6 right-6 z-50 max-w-sm">
      <Card className="shadow-brand" tone="muted" padding="tight">
        <div className={`flex items-center gap-3 rounded-2xl px-4 py-3 text-sm font-semibold ${toneStyles[tone]}`}>
          {message}
        </div>
      </Card>
    </div>
  )
}
