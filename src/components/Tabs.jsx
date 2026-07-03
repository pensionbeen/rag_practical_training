import React from 'react'

export default function Tabs({ active, onChange }) {
  return (
    <nav className="mt-6 border-b border-border">
      <ul className="flex gap-6">
        <li className="pb-3 cursor-pointer" onClick={() => onChange('search')}>
          <div className="flex items-center gap-2">
            <span className="font-mono">§1</span>
            <span className="font-sans">검색</span>
          </div>
          <div className={`mt-2 h-0.5 ${active === 'search' ? 'bg-[var(--accent)]' : 'bg-transparent'}`} />
        </li>
        <li className="pb-3 cursor-pointer" onClick={() => onChange('papers')}>
          <div className="flex items-center gap-2">
            <span className="font-mono">§2</span>
            <span className="font-serif">논문 추천</span>
          </div>
          <div className={`mt-2 h-0.5 ${active === 'papers' ? 'bg-[var(--accent2)]' : 'bg-transparent'}`} />
        </li>
      </ul>
    </nav>
  )
}
