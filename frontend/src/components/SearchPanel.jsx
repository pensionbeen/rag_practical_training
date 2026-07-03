import React, { useState } from 'react'
import { Search, Loader2 } from 'lucide-react'
import { askQuestion } from '../config/api'

export default function SearchPanel() {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState([])
  const [selected, setSelected] = useState(null)
  const [status, setStatus] = useState('empty')
  const [error, setError] = useState(null)

  const handleSearch = async () => {
    if (!query.trim()) {
      setResults([])
      setStatus('empty')
      return
    }

    setLoading(true)
    setError(null)

    try {
      const data = await askQuestion(query)
      setResults([
        {
          id: 'answer',
          title: query,
          snippet: data.response.length > 80 ? `${data.response.slice(0, 80)}...` : data.response,
          content: data.response,
          source: data.source_file,
          fallback: data.fallback_used,
          mergeTargets: data.suggested_merge_targets || []
        }
      ])
      setStatus(data.fallback_used ? 'fallback' : 'rag')
    } catch (err) {
      setError('백엔드 서버에 연결할 수 없습니다. FastAPI 서버(uvicorn backend.main:app)가 실행 중인지 확인해 주세요.')
      setResults([])
      setStatus('error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="search-card">
      <div className="search-row">
        <input
          className="search-input"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
          placeholder="질문을 입력하세요"
        />
        <button type="button" className="search-button" onClick={handleSearch} disabled={loading}>
          {loading ? <span className="spinner" /> : <Search size={16} />}
          검색
        </button>
      </div>

      {status === 'rag' && <div className="status-pill badge-success" style={{ marginTop: 18 }}>RAG 검색 결과</div>}
      {status === 'fallback' && <div className="status-pill badge-warning" style={{ marginTop: 18 }}>옵시디언 지식 베이스에 없음 → AI 지식 폴백</div>}
      {status === 'error' && <div className="status-pill badge-warning" style={{ marginTop: 18 }}>{error}</div>}

      {results.length > 0 ? (
        <div className="note-list" style={{ marginTop: 18 }}>
          {results.map(note => (
            <button key={note.id} type="button" className="note-card" onClick={() => setSelected(note)}>
              <span className="card-line note" />
              <div className="note-card-content">
                <h3 className="note-title">{note.title}</h3>
                <p className="note-snippet">{note.snippet}</p>
                <div className="card-meta">출처: {note.source}</div>
              </div>
              <span className="card-meta" style={{ color: 'var(--accent)' }}>&gt;</span>
            </button>
          ))}
        </div>
      ) : (
        <div className="empty-message" style={{ marginTop: 18 }}>
          검색어를 입력하고 검색 버튼을 눌러 개인 노트 기반 검색 결과를 확인하세요.
        </div>
      )}

      {selected && (
        <div className="modal-backdrop" onClick={() => setSelected(null)}>
          <div className="modal-panel" onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginBottom: 18 }}>
              <div>
                <p className="panel-label">검색 결과 상세</p>
                <h3 className="paper-detail-title" style={{ margin: '6px 0 0' }}>{selected.title}</h3>
              </div>
              <button type="button" className="drawer-close" onClick={() => setSelected(null)}>닫기</button>
            </div>
            <div className="paper-detail-content">{selected.content}</div>
            <div className="paper-detail-meta" style={{ marginTop: 18 }}>출처: {selected.source}</div>
          </div>
        </div>
      )}
    </section>
  )
}
