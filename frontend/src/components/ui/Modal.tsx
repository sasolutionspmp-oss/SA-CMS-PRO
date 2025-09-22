import React from 'react'
import Card from '../patterns/Card'
import Button from './Button'

type Props = { show: boolean; onClose: () => void; children: React.ReactNode; title?: string }

export default function Modal({ show, onClose, children, title }: Props) {
  if (!show) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand-primary/40 backdrop-blur-xl">
      <Card className="w-full max-w-lg" tone="default" padding="relaxed">
        <div className="space-y-6">
          {title && <h2 className="text-2xl font-semibold text-text-primary">{title}</h2>}
          <div className="text-sm text-text-secondary">{children}</div>
          <div className="flex justify-end">
            <Button variant="outline" onClick={onClose}>
              Close
            </Button>
          </div>
        </div>
      </Card>
    </div>
  )
}
