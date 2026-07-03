import React, { useState, useRef, useEffect } from 'react'
import { Loader2, ExternalLink } from 'lucide-react'
import PaperDetailDrawer from './PaperDetailDrawer'

const mockPapers = Array.from({ length: 5 }).map((_, i) => ({
  id: i + 1,
  title: `Sample Paper Title ${i + 1}`,
  authors: 'Kim et al.',
  journal: 'Journal of Examples',
  year: 2023,
  abstract: '이 논문은 예시를 위한 목적으로 작성되었습니다.',
}))

export default function PapersPanel() {
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(false)
  const [papers, setPapers] = useState([])
  const [menu, setMenu] = useState(null) // {x,y,paperIndex}
  const [drawerPaper, setDrawerPaper] = useState(null)

  const doSearch = () => {
    setLoading(true)
    // TODO: DBpia Open API search (XML parsing placeholder)
    setTimeout(() => {
      setPapers(q ? mockPapers : [])
      setLoading(false)
    }, 600)
  }

  useEffect(() => {
    const onClick = () => setMenu(null)
    window.addEventListener('click', onClick)
    return () => window.removeEventListener('click', onClick)
  }, [])

  const onCardClick = (e, index) => {
    e.stopPropagation()
    setMenu({ x: e.clientX, y: e.clientY, paperIndex: index })
  }

  const openDetail = index => {
    setDrawerPaper(papers[index])
    setMenu(null)
  }

  return (
    <section>
      <div className="flex gap-2">
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="키워드를 입력하세요" className="flex-1 p-2 rounded" style={{ border: '1px solid var(--border)' }} />
        <button onClick={doSearch} className="px-4 rounded flex items-center gap-2" style={{ background: 'var(--accent2)', color: 'white' }}>
          {loading ? <Loader2 className="animate-spin" size={16} /> : '추천받기'}
        </button>
      </div>

      <ul className="mt-4 space-y-2">
        {papers.map((p, i) => (
          <li key={p.id} className="p-3 rounded hover:bg-[var(--accent2)]/8 cursor-pointer" style={{ border: '1px solid var(--border)' }} onClick={e => onCardClick(e, i)}>
            <div className="flex items-start gap-3">
              <div style={{ width: 3, background: 'var(--accent2)' }} />
              <div>
                <div className="flex items-center gap-3">
                  <span className="font-mono text-xs">{String(i+1).padStart(2,'0')}</span>
                  <h4 style={{ fontFamily: 'Source Serif 4, serif', margin: 0 }}>{p.title}</h4>
                </div>
                <div className="text-xs font-mono text-[var(--text-3)]">{p.authors} · {p.journal} · {p.year}</div>
              </div>
              <div className="ml-auto">
                <ExternalLink onClick={e => { e.stopPropagation(); /* open external link */ }} />
              </div>
            </div>
          </li>
        ))}
      </ul>

      {menu && (
        <div style={{ position: 'fixed', left: menu.x, top: menu.y, zIndex: 60 }}>
          <div className="bg-white border rounded shadow-sm" style={{ border: '1px solid var(--border)' }}>
            <button className="block w-full text-left px-4 py-2" onClick={() => openDetail(menu.paperIndex)}>초록 보기</button>
            <button className="block w-full text-left px-4 py-2" onClick={() => openDetail(menu.paperIndex)}>목차 보기</button>
          </div>
        </div>
      )}

      <PaperDetailDrawer paper={drawerPaper} onClose={() => setDrawerPaper(null)} />
    </section>
  )
}
