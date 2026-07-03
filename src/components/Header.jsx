import React from 'react'

export default function Header() {
  return (
    <header className="flex items-end justify-between">
      <div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm" style={{ color: 'var(--accent)' }}>●</span>
          <span className="font-mono text-sm" style={{ color: 'var(--accent2)' }}>●</span>
        </div>
        <h1 className="mt-2" style={{ fontFamily: 'Source Serif 4, serif', fontSize: 27, margin: 0 }}>
          공부 도우미
        </h1>
      </div>
      <div className="h-8" />
      <div className="w-full mt-4 border-t-2 border-double border-transparent" />
    </header>
  )
}
