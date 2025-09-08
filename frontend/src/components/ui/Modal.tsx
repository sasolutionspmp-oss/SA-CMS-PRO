import React from 'react'

type Props = { show: boolean; onClose: () => void; children: React.ReactNode }

export default function Modal({ show, onClose, children }: Props) {
  if (!show) return null
  return (
    <div className="fixed inset-0 flex items-center justify-center bg-black/50">
      <div className="bg-white p-4">
        {children}
        <button onClick={onClose} className="mt-2 px-2 py-1 border">
          Close
        </button>
      </div>
    </div>
  )
}
