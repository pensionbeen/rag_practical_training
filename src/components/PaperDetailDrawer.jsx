import React from 'react'

export default function PaperDetailDrawer({ paper, onClose }) {
  return (
    <div className={`fixed top-0 right-0 h-full w-96 transform ${paper ? 'translate-x-0' : 'translate-x-full'} transition-transform duration-200`} style={{ background: 'white', borderLeft: '1px solid var(--border)' }}>
      <div className="p-4">
        <div className="flex justify-between items-start">
          <div>
            <h3 style={{ fontFamily: 'Source Serif 4, serif' }}>{paper ? paper.title : ''}</h3>
            <div className="text-xs font-mono text-[var(--text-3)]">{paper ? `${paper.authors} · ${paper.journal} · ${paper.year}` : ''}</div>
          </div>
          <div>
            <button onClick={onClose}>닫기</button>
          </div>
        </div>
        <div className="mt-4" style={{ fontFamily: 'Source Serif 4, serif' }}>{paper ? <p>{paper.abstract}</p> : <p className="text-[var(--text-2)]">선택된 논문이 없습니다.</p>}</div>
      </div>
    </div>
  )
}
