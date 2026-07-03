import React, { useState } from 'react'
import { Search, Loader2 } from 'lucide-react'

// Mock data for RAG search results
const mockResults = [
  { id: 1, title: '옵시디언 노트: 공부 계획', snippet: '이 노트는 공부 계획과 요약을 포함합니다.', source: 'vault/notes/plans.md' },
  { id: 2, title: '토픽별 요약: 인공지능', snippet: '머신러닝 기본 개념과 정리...', source: 'vault/notes/ai.md' },
]

export default function SearchPanel() {
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState([])
  const [modal, setModal] = useState(null)

  const doSearch = async () => {
    setLoading(true)
    // TODO: call RAG search API first; fallback to OpenAI API if no results
    setTimeout(() => {
      const found = q ? mockResults : []
      setResults(found)
      setLoading(false)
    }, 600)
  }

  return (
    <section>
      <div className="flex gap-2">
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="검색어를 입력하세요" className="flex-1 p-2 rounded" style={{ border: '1px solid var(--border)' }} />
        <button onClick={doSearch} className="px-4 rounded flex items-center gap-2" style={{ background: 'var(--accent)', color: 'white' }}>
          {loading ? <Loader2 className="animate-spin" size={16} /> : <Search size={16} />}
          검색
        </button>
      </div>

      <div className="mt-4">
        {results.length > 0 ? (
          <div>
            <div className="px-3 py-2 text-sm font-medium inline-block rounded" style={{ background: '#eef2ff', color: 'var(--accent)' }}>RAG 검색 결과</div>
            <ul className="mt-3 space-y-2">
              {results.map(r => (
                <li key={r.id} className="p-3 rounded hover:bg-[var(--accent)]/8 cursor-pointer" style={{ border: '1px solid var(--border)' }} onClick={() => setModal(r)}>
                  <div className="flex items-start gap-3">
                    <div style={{ width: 3, background: 'var(--accent)' }} />
                    <div>
                      <div className="font-semibold">{r.title}</div>
                      <div className="text-sm text-[var(--text-2)]">{r.snippet}</div>
                      <div className="text-xs font-mono text-[var(--text-3)] mt-1">{r.source}</div>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <div className="mt-4 flex items-center gap-2">
            <div className="px-3 py-2 text-sm rounded" style={{ background: 'var(--amber)', color: 'white' }}>RAG 결과 없음 → OpenAI 폴백</div>
          </div>
        )}
      </div>

      {modal && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center" onClick={() => setModal(null)}>
          <div className="bg-white max-w-2xl w-full p-6 rounded" onClick={e => e.stopPropagation()}>
            <div className="flex justify-between items-start">
              <h3 style={{ fontFamily: 'Source Serif 4, serif' }}>{modal.title}</h3>
              <button onClick={() => setModal(null)}>닫기</button>
            </div>
            <p className="mt-3 text-[var(--text-2)]">{modal.snippet}</p>
            <div className="mt-4 text-xs font-mono text-[var(--text-3)]">출처: {modal.source}</div>
          </div>
        </div>
      )}
    </section>
  )
}
