import React, { useState, useEffect } from 'react'
import { Loader2 } from 'lucide-react'
import { getSimilarDocs } from '../config/api'

export default function PaperDetailDrawer({ paper, type, onClose, onSave, folders, vaultPath, searchQuery }) {
  const [saveMode, setSaveMode] = useState('merge') // 'merge' or 'new'
  const [similarConcepts, setSimilarConcepts] = useState([])
  const [selectedConcept, setSelectedConcept] = useState('')
  const [conceptName, setConceptName] = useState('')
  const [selectedCat, setSelectedCat] = useState('루트')
  const [customCat, setCustomCat] = useState('')
  const [saving, setSaving] = useState(false)

  // Initialize values when paper changes
  useEffect(() => {
    if (paper) {
      setConceptName(paper.title || '')
      
      // Fetch top 5 similar concept notes based on search query or paper title
      const fetchSimilar = async () => {
        try {
          const searchTarget = searchQuery || paper.title
          const similar = await getSimilarDocs(searchTarget, vaultPath || null)
          setSimilarConcepts(similar)
          if (similar.length > 0) {
            setSelectedConcept(similar[0])
            setSaveMode('merge')
          } else {
            setSelectedConcept('')
            setSaveMode('new')
          }
        } catch (err) {
          console.error('Failed to fetch similar concepts for paper:', err)
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
  }, [paper, vaultPath, searchQuery])

  const handleSave = async () => {
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

    setSaving(true)

    const formattedContent = `### 📚 관련 학술 논문 출처: ${paper.title}
- **저자**: ${paper.authors || paper.meta || '미상'}
- **링크**: ${paper.link || ''}
- **AI 번역 요약**: ${paper.summary || paper.abstract || '요약 없음'}
`

    try {
      await onSave(nameToSave, formattedContent, catToSave)
      alert('성공적으로 옵시디언 노트에 논문이 병합/저장되었습니다!')
      onClose()
    } catch (err) {
      alert('저장 실패: ' + err.message)
    } finally {
      setSaving(false)
    }
  }

  if (!paper) {
    return null
  }

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className={`paper-detail-drawer drawer-open`} style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        <div style={{ flex: '1', overflowY: 'auto', paddingBottom: 20 }}>
          <div className="drawer-header" style={{ paddingBottom: 10 }}>
            <div>
              <p className="paper-detail-type">{type === 'abstract' ? '초록 보기' : '목차 보기'}</p>
              <h3 className="paper-detail-title" style={{ fontSize: '1.25rem' }}>{paper.title}</h3>
            </div>
            <button type="button" className="drawer-close" onClick={onClose}>닫기</button>
          </div>
          <div className="paper-detail-meta" style={{ marginBottom: 16 }}>{paper.authors || paper.meta}</div>
          <div className="paper-detail-content" style={{ fontSize: '0.92rem', lineHeight: '1.6', background: 'var(--bg)', padding: 14, borderRadius: 6 }}>
            {type === 'abstract' ? (paper.summary || paper.abstract) : (paper.toc || '목차가 제공되지 않는 논문입니다.')}
          </div>
        </div>

        <div style={{ borderTop: '1px solid var(--border)', paddingTop: 18, marginTop: 'auto' }}>
          <p className="panel-label" style={{ marginBottom: 12 }}>💾 옵시디언 노트에 추가 및 병합</p>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {/* SaveMode Tab Buttons */}
            <div style={{ display: 'flex', border: '1px solid var(--border)', borderRadius: '4px', overflow: 'hidden', marginBottom: 4 }}>
              <button
                type="button"
                style={{
                  flex: 1,
                  padding: '6px',
                  fontSize: '0.75rem',
                  border: 'none',
                  background: saveMode === 'merge' ? 'var(--accent2)' : 'var(--bg)',
                  color: saveMode === 'merge' ? 'white' : 'var(--text-2)',
                  fontWeight: 'bold'
                }}
                onClick={() => setSaveMode('merge')}
              >
                기존 노트에 병합
              </button>
              <button
                type="button"
                style={{
                  flex: 1,
                  padding: '6px',
                  fontSize: '0.75rem',
                  border: 'none',
                  background: saveMode === 'new' ? 'var(--accent2)' : 'var(--bg)',
                  color: saveMode === 'new' ? 'white' : 'var(--text-2)',
                  fontWeight: 'bold'
                }}
                onClick={() => setSaveMode('new')}
              >
                새 노트로 저장
              </button>
            </div>

            {saveMode === 'merge' ? (
              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-2)', display: 'block', marginBottom: 4 }}>병합할 기존 개념 노트 선택 (유사도순 상위 5개)</label>
                <select
                  className="drawer-input"
                  style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'white' }}
                  value={selectedConcept}
                  onChange={e => setSelectedConcept(e.target.value)}
                >
                  {similarConcepts.length > 0 ? (
                    similarConcepts.map(c => <option key={c} value={c}>⭐ {c}</option>)
                  ) : (
                    <option value="">(연관 개념을 찾는 중이거나 없습니다)</option>
                  )}
                </select>
              </div>
            ) : (
              <>
                <div>
                  <label style={{ fontSize: '0.8rem', color: 'var(--text-2)', display: 'block', marginBottom: 4 }}>새로 저장할 개념명</label>
                  <input
                    className="drawer-input"
                    style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}
                    value={conceptName}
                    onChange={e => setConceptName(e.target.value)}
                    placeholder="예: 배치 정규화"
                  />
                </div>

                <div>
                  <label style={{ fontSize: '0.8rem', color: 'var(--text-2)', display: 'block', marginBottom: 4 }}>카테고리 선택</label>
                  <select
                    className="drawer-input"
                    style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'white' }}
                    value={selectedCat}
                    onChange={e => setSelectedCat(e.target.value)}
                  >
                    <option value="루트">루트 (폴더 없음)</option>
                    {folders.map(folder => (
                      <option key={folder} value={folder}>{folder}</option>
                    ))}
                    <option value="직접 입력">직접 입력 (새 폴더 생성)</option>
                  </select>
                </div>

                {selectedCat === '직접 입력' && (
                  <div>
                    <label style={{ fontSize: '0.8rem', color: 'var(--text-2)', display: 'block', marginBottom: 4 }}>새 카테고리명 입력</label>
                    <input
                      className="drawer-input"
                      style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}
                      value={customCat}
                      onChange={e => setCustomCat(e.target.value)}
                      placeholder="예: 인공지능/딥러닝"
                    />
                  </div>
                )}
              </>
            )}

            <button
              type="button"
              className="drawer-button"
              style={{
                width: '100%',
                padding: '10px',
                background: 'var(--accent2)',
                color: 'white',
                border: 'none',
                borderRadius: 'var(--radius)',
                fontWeight: 'bold',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 8,
                marginTop: 6
              }}
              onClick={handleSave}
              disabled={saving}
            >
              {saving ? <Loader2 className="spinner" size={16} /> : null}
              {saveMode === 'merge' ? '기존 노트에 병합하기' : '새 개념 노트로 저장'}
            </button>
          </div>
        </div>
      </aside>
    </>
  )
}
