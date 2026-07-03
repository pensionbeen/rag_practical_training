import React from 'react'

export default function PaperDetailDrawer({ paper, type, onClose }) {
  if (!paper) {
    return null
  }

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className={`paper-detail-drawer drawer-open`}>
        <div className="drawer-header">
          <div>
            <p className="paper-detail-type">{type === 'abstract' ? '초록 보기' : '목차 보기'}</p>
            <h3 className="paper-detail-title">{paper.title}</h3>
          </div>
          <button type="button" className="drawer-close" onClick={onClose}>닫기</button>
        </div>
        <div className="paper-detail-meta">{paper.meta}</div>
        <div className="paper-detail-content">{type === 'abstract' ? paper.abstract : paper.toc}</div>
      </aside>
    </>
  )
}
