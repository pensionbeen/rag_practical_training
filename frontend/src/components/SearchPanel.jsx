import React, { useState, useEffect, useRef } from 'react'
import { Search, Loader2, ExternalLink } from 'lucide-react'
import { askQuestion, saveConcept, saveReviewNote, getFolders, getSimilarDocs, reindexVault } from '../config/api'

export default function SearchPanel({ vaultPath }) {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState([])
  const [selected, setSelected] = useState(null)
  const [status, setStatus] = useState('empty')
  const [error, setError] = useState(null)

  // Obsidian saving states
  const [folders, setFolders] = useState([])
  const [similarConcepts, setSimilarConcepts] = useState([])
  const [saveMode, setSaveMode] = useState('merge') // 'merge' or 'new'
  const [selectedConcept, setSelectedConcept] = useState('')
  const [conceptName, setConceptName] = useState('')
  const [selectedCat, setSelectedCat] = useState('루트')
  const [customCat, setCustomCat] = useState('')
  const [savingConcept, setSavingConcept] = useState(false)
  const [savingReview, setSavingReview] = useState(false)
  const abortControllerRef = useRef(null)

  // Load folders on mount or vaultPath change
  useEffect(() => {
    const fetchFolders = async () => {
      try {
        const folderList = await getFolders(vaultPath || null)
        setFolders(folderList)
      } catch (err) {
        console.error('Failed to load folders:', err)
      }
    }
    fetchFolders()
  }, [vaultPath])

  // When selected changes, fetch the top 5 similar concepts for the query/title
  useEffect(() => {
    let cancelled = false

    if (selected) {
      setConceptName(selected.title)

      const fetchSimilar = async () => {
        try {
          const similar = await getSimilarDocs(selected.title, vaultPath || null)
          if (cancelled) return
          setSimilarConcepts(similar)
          if (similar.length > 0) {
            setSelectedConcept(similar[0])
            setSaveMode('merge')
          } else {
            setSelectedConcept('')
            setSaveMode('new')
          }
        } catch (err) {
          if (cancelled) return
          console.error('Failed to fetch similar concepts:', err)
          setSimilarConcepts([])
          setSaveMode('new')
        }
      }
      fetchSimilar()
    } else {
      setConceptName('')
      setSelectedConcept('')
      setSimilarConcepts([])
    }

    return () => {
      cancelled = true
    }
  }, [selected, vaultPath])

  // Esc 키로 검색 결과 상세 모달 닫기
  useEffect(() => {
    if (!selected) return

    const handleKeyDown = e => {
      if (e.key === 'Escape') {
        setSelected(null)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selected])

  const handleSearch = async () => {
    if (loading) return

    if (!query.trim()) {
      setResults([])
      setStatus('empty')
      return
    }

    const controller = new AbortController()
    abortControllerRef.current = controller

    setLoading(true)
    setError(null)

    try {
      const data = await askQuestion(query, vaultPath || null, controller.signal)
      setResults([
        {
          id: 'answer',
          title: data.suggested_title || query,
          snippet: data.response.length > 80 ? `${data.response.slice(0, 80)}...` : data.response,
          content: data.response,
          source: data.source_file,
          fallback: data.fallback_used,
          mergeTargets: data.suggested_merge_targets || [],
          obsidianUri: data.obsidian_uri,
          savedPapers: data.saved_papers || []
        }
      ])
      setStatus(data.fallback_used ? 'fallback' : 'rag')
    } catch (err) {
      if (err.name === 'AbortError') {
        setStatus('empty')
      } else if (err instanceof TypeError) {
        // fetch가 아예 연결에 실패한 경우 (서버 다운, 네트워크 오류 등)
        setError('백엔드 서버에 연결할 수 없습니다. FastAPI 서버(uvicorn backend.main:app)가 실행 중인지 확인해 주세요.')
        setResults([])
        setStatus('error')
      } else {
        // 서버는 응답했지만 에러를 반환한 경우 (4xx/5xx) - 실제 원인을 보여준다
        setError(`검색 중 오류가 발생했습니다${err.status ? ` (HTTP ${err.status})` : ''}: ${err.message}`)
        setResults([])
        setStatus('error')
      }
    } finally {
      setLoading(false)
      abortControllerRef.current = null
    }
  }

  const handleCancelSearch = () => {
    abortControllerRef.current?.abort()
  }

  const handleSaveConcept = async () => {
    let nameToSave = ''
    let catToSave = null

    if (saveMode === 'merge') {
      if (!selectedConcept) {
        alert('병합할 기존 개념 노트를 선택해 주세요.')
        return
      }
      nameToSave = selectedConcept
    } else {
      if (!conceptName.trim()) {
        alert('저장할 개념 이름을 입력해 주세요.')
        return
      }
      nameToSave = conceptName.trim()
      catToSave = selectedCat === '직접 입력' ? customCat.trim() : (selectedCat === '루트' ? '' : selectedCat)
    }

    setSavingConcept(true)

    try {
      await saveConcept(nameToSave, selected.content, catToSave, vaultPath || null)
      await reindexVault(vaultPath || null)
      alert('성공적으로 옵시디언 개념 노트에 저장/병합했습니다!')
      
      // Refresh folders
      const folderList = await getFolders(vaultPath || null)
      setFolders(folderList)
      setSelected(null)
    } catch (err) {
      alert('개념 저장 실패: ' + err.message)
    } finally {
      setSavingConcept(false)
    }
  }

  const handleSaveReview = async () => {
    setSavingReview(true)
    try {
      await saveReviewNote(query, selected.content, selected.source, vaultPath || null)
      alert('성공적으로 복습 필요 리스트에 추가되었습니다!')
      setSelected(null)
    } catch (err) {
      alert('복습 추가 실패: ' + err.message)
    } finally {
      setSavingReview(false)
    }
  }

  // Check if Obsidian link is available
  const isObsidianLinkAvailable = !!(selected && selected.obsidianUri)
  
  // Format source file path for user display (e.g. C:\...\ObsiRAG\인공지능\딥러닝\배치 정규화.md -> 인공지능/딥러닝/배치 정규화.md)
  const getDisplaySource = (source) => {
    if (!source) return 'Unknown'
    if (source.includes('None')) return 'LLM Fallback 지식'
    const match = source.match(/ObsiRAG[\\/](.*)$/i)
    return match ? match[1].replace(/\\/g, '/') : source
  }

  const obsidianUri = isObsidianLinkAvailable ? selected.obsidianUri : ''

  return (
    <section className="search-card">
      <div className="search-row">
        <input
          className="search-input"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
          placeholder="질문을 입력하세요"
          disabled={loading}
        />
        <button
          type="button"
          className="search-button"
          onClick={loading ? handleCancelSearch : handleSearch}
          title={loading ? '검색 중지' : '검색'}
        >
          {loading ? <span className="spinner" /> : <Search size={16} />}
          {loading ? '중지' : '검색'}
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
                <div className="card-meta">출처: {getDisplaySource(note.source)}</div>
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
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginBottom: 14 }}>
              <div>
                <p className="panel-label">검색 결과 상세</p>
                <h3 className="paper-detail-title" style={{ margin: '6px 0 0', fontSize: '1.25rem' }}>{selected.title}</h3>
              </div>
              <button type="button" className="drawer-close" onClick={() => setSelected(null)}>닫기</button>
            </div>

            <div className="modal-body">
              <div className="modal-main">
                <div className="paper-detail-content" style={{ whiteSpace: 'pre-wrap', lineHeight: '1.6', background: 'var(--bg)', padding: '16px', borderRadius: '6px', fontSize: '0.95rem' }}>
                  {selected.content}
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12 }}>
                  <div className="paper-detail-meta" style={{ margin: 0 }}>출처: {getDisplaySource(selected.source)}</div>
                  {isObsidianLinkAvailable && (
                    <a
                      href={obsidianUri}
                      className="outline-button"
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 6,
                        fontSize: '0.8rem',
                        padding: '6px 12px',
                        textDecoration: 'none',
                        color: 'var(--accent)',
                        border: '1px solid var(--accent)',
                        borderRadius: '4px',
                        fontWeight: 'bold',
                        background: 'transparent'
                      }}
                    >
                      <ExternalLink size={12} />
                      옵시디언에서 파일 열기
                    </a>
                  )}
                </div>

                {selected.savedPapers && selected.savedPapers.length > 0 && (
                  <div style={{ marginTop: 20, borderTop: '1px solid var(--border)', paddingTop: 14 }}>
                    <p className="panel-label" style={{ marginBottom: 10 }}>📚 연동된 학술 논문 출처</p>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {selected.savedPapers.map((paper, idx) => (
                        <div key={idx} style={{ background: 'var(--bg)', padding: '10px 14px', borderRadius: '4px', border: '1px solid var(--border)' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 }}>
                            <h4 style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text)' }}>{paper.title}</h4>
                            {paper.link && (
                              <a href={paper.link} target="_blank" rel="noreferrer" style={{ fontSize: '0.75rem', color: 'var(--accent)', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 2, fontWeight: 'bold' }}>
                                원문 <ExternalLink size={10} />
                              </a>
                            )}
                          </div>
                          <p style={{ margin: '4px 0 0', fontSize: '0.75rem', color: 'var(--text-2)' }}>저자: {paper.authors}</p>
                          {paper.summary && (
                            <p style={{ margin: '6px 0 0', fontSize: '0.8rem', color: 'var(--text-2)', lineHeight: '1.4', background: 'rgba(0,0,0,0.02)', padding: '6px 10px', borderRadius: '4px' }}>{paper.summary}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="modal-side">
                <p className="panel-label">💾 옵시디언 연동 제어</p>

                {/* 개념 노트 저장 섹션 */}
                <div className="obsidian-col">
                  <label className="section-label">개념 노트 저장</label>

                  <div className="save-mode-tabs">
                    <button
                      type="button"
                      className={`save-mode-tab${saveMode === 'merge' ? ' active' : ''}`}
                      onClick={() => setSaveMode('merge')}
                    >
                      기존 노트에 병합
                    </button>
                    <button
                      type="button"
                      className={`save-mode-tab${saveMode === 'new' ? ' active' : ''}`}
                      onClick={() => setSaveMode('new')}
                    >
                      새 노트로 저장
                    </button>
                  </div>

                  <div className="save-fields">
                    {saveMode === 'merge' ? (
                      <>
                        <label className="field-label">병합할 기존 개념 노트 선택 (유사도순 상위 5개)</label>
                        <select
                          className="drawer-input"
                          value={selectedConcept}
                          onChange={e => setSelectedConcept(e.target.value)}
                        >
                          {similarConcepts.length === 0 ? (
                            <option value="">(연관 개념을 찾는 중이거나 없습니다)</option>
                          ) : (
                            similarConcepts.map(c => (
                              <option key={c} value={c}>⭐ {c}</option>
                            ))
                          )}
                        </select>
                      </>
                    ) : (
                      <>
                        <label className="field-label">새로 저장할 개념명</label>
                        <input
                          className="drawer-input"
                          value={conceptName}
                          onChange={e => setConceptName(e.target.value)}
                          placeholder="예: 배치 정규화"
                        />
                        <label className="field-label">추천 저장 카테고리 지정</label>
                        <select
                          className="drawer-input"
                          value={selectedCat}
                          onChange={e => setSelectedCat(e.target.value)}
                        >
                          <option value="루트">루트 (폴더 없음)</option>
                          {folders.map(folder => (
                            <option key={folder} value={folder}>{folder}</option>
                          ))}
                          <option value="직접 입력">직접 입력 (새 폴더)</option>
                        </select>

                        {selectedCat === '직접 입력' && (
                          <input
                            className="drawer-input"
                            value={customCat}
                            onChange={e => setCustomCat(e.target.value)}
                            placeholder="분류 경로 (예: 인공지능/딥러닝)"
                          />
                        )}
                      </>
                    )}
                  </div>

                  <button
                    type="button"
                    className="obsidian-submit-button"
                    onClick={handleSaveConcept}
                    disabled={savingConcept}
                  >
                    {savingConcept ? <Loader2 className="spinner" size={14} /> : null}
                    {saveMode === 'merge' ? '기존 노트에 병합하기' : '새 개념 노트로 저장'}
                  </button>
                </div>

                {/* 복습 필요 리스트 섹션 */}
                <div className="obsidian-col">
                  <label className="section-label">복습 리스트 추가</label>
                  <p className="field-label" style={{ lineHeight: '1.4', margin: 0 }}>
                    질문과 현재 답변을 옵시디언의 '복습_필요_리스트.md' 파일에 자동으로 가공 및 추가 기입합니다.
                  </p>

                  <button
                    type="button"
                    className="review-button"
                    onClick={handleSaveReview}
                    disabled={savingReview}
                  >
                    {savingReview ? <Loader2 className="spinner" size={14} /> : null}
                    복습 리스트에 기입
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
