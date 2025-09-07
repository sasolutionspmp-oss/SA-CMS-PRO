import React from 'react'

type Props = { message: string }

export default function Toast({ message }: Props) {
  return <div className="fixed bottom-2 right-2 bg-gray-700 text-white px-2 py-1">{message}</div>
}
