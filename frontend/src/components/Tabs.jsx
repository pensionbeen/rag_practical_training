import React from 'react'

export default function Tabs({ active, onChange }) {
  return (
    <div className="tabs">
      <button type="button" className={`tab-button ${active === 'search' ? 'active search' : ''}`} onClick={() => onChange('search')}>
        <span>§1</span>
        <span>검색</span>
      </button>
      <button type="button" className={`tab-button ${active === 'papers' ? 'active papers' : ''}`} onClick={() => onChange('papers')}>
        <span>§2</span>
        <span>논문 추천</span>
      </button>
    </div>
  )
}
