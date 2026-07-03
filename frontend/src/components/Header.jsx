import React from 'react'

export default function Header() {
  return (
    <header className="header">
      <div className="eyebrow">
        <span className="eyebrow-dot blue" />
        <span className="eyebrow-dot red" />
        <span>검색 / 논문</span>
      </div>
      <h1 className="header-title">공부 도우미</h1>
    </header>
  )
}
