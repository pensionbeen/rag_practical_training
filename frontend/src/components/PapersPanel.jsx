import React, { useEffect, useRef, useState } from 'react'
import { Loader2 } from 'lucide-react'
import PaperDetailDrawer from './PaperDetailDrawer'
import { searchPapers, saveConcept, getFolders, getConcepts, reindexVault } from '../config/api'

const mockPapers = [
  {
    id: 1,
    index: '01',
    title: '한국 학술정보 서비스의 DBpia 데이터 활용 연구',
    meta: '김지훈 · 한국정보학회 · 2024',
    abstract: 'DBpia는 국내 학술지 데이터를 제공하는 대표 서비스로, 연구자들이 논문 검색과 인용 정보를 빠르게 찾을 수 있도록 지원합니다.',
    toc: '1. 서론\n2. 관련 연구\n3. 데이터 구조\n4. 활용 사례\n5. 결론',
    link: 'https://www.dbpia.co.kr'
  },
  {
    id: 2,
    index: '02',
    title: 'RAG 기반 개인 학습 보조 시스템 설계',
    meta: '이지연 · 학습과 AI · 2025',
    abstract: '개인화된 학습 어시스턴트를 위해 RAG와 옵시디언 노트 데이터의 결합을 제안합니다.',
    toc: '1. 개념 정의\n2. 시스템 아키텍처\n3. 구현 방법\n4. 평가\n5. 향후 연구',
    link: 'https://www.dbpia.co.kr'
  },
  {
    id: 3,
    index: '03',
    title: '논문 추천 알고리즘에서 메타데이터의 역할',
    meta: '박수현 · 데이터마이닝리뷰 · 2023',
    abstract: '저자 정보를 활용하여 사용자 맞춤 추천 정확도를 높이는 메타데이터 최적화 방법을 제시합니다.',
    toc: '1. 추천 모델\n2. 메타데이터 분석\n3. 실험 결과\n4. 토의',
    link: 'https://www.dbpia.co.kr'
  },
  {
    id: 4,
    index: '04',
    title: '학술 검색의 품질 개선을 위한 키워드 확장 기법',
    meta: '윤한별 · 정보검색학회지 · 2024',
    abstract: '키워드 확장을 통해 관련 논문을 더 정확하게 찾아내는 방법과 실험 결과를 정리합니다.',
    toc: '1. 키워드 확장\n2. 구현\n3. 사례 분석\n4. 결론',
    link: 'https://www.dbpia.co.kr'
  },
  {
    id: 5,
    index: '05',
    title: '인용 네트워크 분석을 활용한 연구 주제 탐색',
    meta: '최민수 · 연구방법론 · 2022',
    abstract: '인용 정보는 연구 주제 간 연결 관계를 보여주며, 탐색적인 연구에 중요한 단서를 제공합니다.',
    toc: '1. 네트워크 구조\n2. 분석 기법\n3. 사례 연구\n4. 확장 방향',
    link: 'https://www.dbpia.co.kr'
  }
]

export default function PapersPanel({ vaultPath }) {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [papers, setPapers] = useState([])
  const [folders, setFolders] = useState([])
  const [concepts, setConcepts] = useState([])
  const [menu, setMenu] = useState(null)
  const [activePaper, setActivePaper] = useState(null)
  const [detailType, setDetailType] = useState('abstract')
  const abortControllerRef = useRef(null)

  const fetchDataList = async () => {
    try {
      const [folderList, conceptList] = await Promise.all([
        getFolders(vaultPath || null),
        getConcepts(vaultPath || null)
      ])
      setFolders(folderList)
      setConcepts(conceptList)
    } catch (err) {
      console.error('Failed to load folders/concepts:', err)
    }
  }

  useEffect(() => {
    const handleWindowClick = () => setMenu(null)
    window.addEventListener('click', handleWindowClick)
    
    fetchDataList()

    return () => window.removeEventListener('click', handleWindowClick)
  }, [vaultPath])

  const handleSearch = async () => {
    if (loading) return
    if (!query.trim()) return

    const controller = new AbortController()
    abortControllerRef.current = controller

    setLoading(true)
    try {
      const data = await searchPapers(query.trim(), controller.signal)
      const mapped = data.map((item, idx) => ({
        id: idx + 1,
        index: String(idx + 1).padStart(2, '0'),
        title: item.title,
        meta: `${item.authors || '미상'} · ArXiv · ${item.published ? item.published.slice(0, 10) : ''}`,
        abstract: item.summary,
        toc: '학술 논문의 초록(Abstract) 요약 내용이 서랍 하단에 표시되며, 이를 옵시디언에 직접 병합 및 추가 저장할 수 있습니다.',
        link: item.link,
        authors: item.authors,
        summary: item.summary
      }))
      setPapers(mapped)
    } catch (err) {
      if (err.name !== 'AbortError') {
        alert('논문 검색 실패: ' + err.message)
      }
    } finally {
      setLoading(false)
      abortControllerRef.current = null
    }
  }

  const handleCancelSearch = () => {
    abortControllerRef.current?.abort()
  }

  const handleSaveConcept = async (conceptName, content, category) => {
    await saveConcept(conceptName, content, category, vaultPath || null)
    await reindexVault(vaultPath || null) // RAG 동기화
    await fetchDataList()
  }

  const openPaperMenu = (event, paper) => {
    event.stopPropagation()
    setMenu({ x: event.clientX, y: event.clientY, paper })
  }

  const openPaperDetail = type => {
    if (!menu) return
    setDetailType(type)
    setActivePaper(menu.paper)
    setMenu(null)
  }

  return (
    <section className="search-card">
      <div className="panel-top">
        <p className="panel-label">DBpia Open API 논문 추천</p>
      </div>
      <div className="paper-row">
        <input
          className="paper-input"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
          placeholder="연구 키워드를 입력하세요"
          disabled={loading}
        />
        <button
          type="button"
          className="paper-button"
          onClick={loading ? handleCancelSearch : handleSearch}
          title={loading ? '검색 중지' : '추천받기'}
        >
          {loading ? <span className="spinner" /> : null}
          {loading ? '중지' : '추천받기'}
        </button>
      </div>

      {papers.length === 0 ? (
        <div className="empty-message" style={{ marginTop: 18 }}>
          키워드를 입력하고 추천받기 버튼을 눌러 논문 목록을 확인하세요.
        </div>
      ) : (
        <div className="paper-list" style={{ marginTop: 18 }}>
          {papers.map(paper => (
            <div key={paper.id} className="paper-card" onClick={e => openPaperMenu(e, paper)}>
              <span className="card-line paper" />
              <div className="paper-card-content">
                <div className="paper-index">{paper.index}</div>
                <h3 className="paper-title">{paper.title}</h3>
                <div className="paper-meta">{paper.meta}</div>
              </div>
              <a
                href={paper.link}
                target="_blank"
                rel="noreferrer"
                className="paper-link"
                onClick={e => e.stopPropagation()}
              >
                원문
              </a>
            </div>
          ))}
        </div>
      )}

      {menu && (
        <div className="paper-menu" style={{ left: menu.x, top: menu.y }}>
          <button type="button" onClick={() => openPaperDetail('abstract')}>초록 보기</button>
          <button type="button" onClick={() => openPaperDetail('toc')}>목차 보기</button>
        </div>
      )}

      <PaperDetailDrawer
        paper={activePaper}
        type={detailType}
        onClose={() => setActivePaper(null)}
        onSave={handleSaveConcept}
        folders={folders}
        concepts={concepts}
        vaultPath={vaultPath}
        searchQuery={query}
      />
    </section>
  )
}
