# ObsiRAG — 옵시디언 연동형 RAG 시스템

외부 문서(PDF/TXT)를 업로드하면 핵심 개념을 추출해 옵시디언(Obsidian) 볼트에 마크다운 노트로 자동 정리하고,
그 지식 베이스를 바탕으로 출처 기반 Q&A 및 복습 노트 관리를 제공하는 RAG(Retrieval-Augmented Generation) 시스템입니다.

## 폴더 구조

```
.
├── backend/            FastAPI 백엔드 (Core RAG) + Streamlit 프로토타입 UI
│   ├── main.py          API 서버 (인덱싱 · 검색 · 옵시디언 파일 입출력)
│   ├── pdf_parser.py     PDF 파싱 및 청킹 모듈
│   └── ObsiRAG.py       Streamlit 기반 단독 프로토타입 (main.py API를 호출)
├── frontend/           React + Vite 웹 프론트엔드 (정식 팀 프론트엔드)
│   ├── src/
│   └── ...
├── docs/               설계 문서 및 팀 협업 규칙
├── examples/           실습용 독립 CLI 스크립트 (제품 코드와 무관, 학습 목적)
└── my_obsidian_vault/  로컬 옵시디언 볼트(데이터) 기본 경로
```

## 아키텍처

- **backend/main.py**: FastAPI 서버. 옵시디언 볼트의 마크다운 문서를 읽어 FAISS로 인덱싱하고,
  질문에 대해 근거 기반 답변을 생성합니다. 인터페이스 규격은 [docs/TEAM_INTERFACE_RULES.md](docs/TEAM_INTERFACE_RULES.md)를 따릅니다.
- **frontend/**: 백엔드 API(`/api/v1/ask`, `/api/v1/obsidian/save*`)를 호출하는 React 웹 UI.
- **backend/ObsiRAG.py**: 동일한 백엔드 API를 호출하는 Streamlit 프로토타입(대안 UI). 데모/빠른 확인용입니다.
- **backend/pdf_parser.py**: PDF를 문맥 보존 청크로 변환하는 공용 모듈.

## 요구 사항

- Python 3.10+
- Node.js 18+
- OpenAI API Key ([OpenAI Platform](https://platform.openai.com/api-keys)에서 발급)

## 설치

```bash
# 1) Python 가상환경 & 백엔드 의존성
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

# 2) 프론트엔드 의존성
cd frontend
npm install
cd ..
```

프로젝트 루트에 `.env` 파일을 만들고 API 키를 설정합니다 (`.gitignore`에 등록되어 있어 커밋되지 않습니다):

```
OPENAI_API_KEY=your_openai_api_key_here
```

## 실행

모든 명령은 **저장소 루트에서** 실행합니다 (경로 기본값이 루트 기준으로 계산되기 때문입니다).

**백엔드 API 서버**
```bash
uvicorn backend.main:app --reload --port 8000
```

**프론트엔드 (React)**
```bash
cd frontend
npm run dev
```

**Streamlit 프로토타입 (선택)** — 백엔드 서버가 함께 떠 있어야 합니다.
```bash
streamlit run backend/ObsiRAG.py
```

## 문서

- [docs/MY_CORE_RAG_PLAN.md](docs/MY_CORE_RAG_PLAN.md) — Core RAG 백엔드 개발 상태/계획
- [docs/TEAM_INTERFACE_RULES.md](docs/TEAM_INTERFACE_RULES.md) — 팀 간 API 인터페이스 규약
- [docs/obsidian_rag_rules.md](docs/obsidian_rag_rules.md) — 기능별 상세 동작 규칙

## examples/

`rag_practical.py`, `rag_document_helper.py`는 RAG 파이프라인(청킹 → 임베딩 → FAISS → 검색 → 생성)을 익히기 위한
독립 실행형 학습 스크립트입니다. 제품 코드(backend/frontend)와는 별개이며 참고용으로만 유지합니다.

```bash
python examples/rag_practical.py
python examples/rag_document_helper.py
```
