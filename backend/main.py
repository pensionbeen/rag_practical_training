import os
import re
import asyncio
import hashlib
from io import BytesIO
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_openai import ChatOpenAI

from .pdf_parser import parse_pdf_to_chunks

# 환경 변수 로드
load_dotenv()

if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("OPENAI_API_KEY environment variable is not set.")

app = FastAPI(title="ObsiRAG Backend Server", version="1.0.0")

# CORS 설정 (프론트엔드 호환성 확보)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 옵시디언 볼트 경로 설정
VAULT_PATH = Path.cwd() / "my_obsidian_vault"
VAULT_PATH.mkdir(parents=True, exist_ok=True)

# 파일 쓰기 충돌 방지를 위한 Lock 객체
file_write_lock = asyncio.Lock()

# 임베딩 모델 및 LLM 초기화
embeddings = HuggingFaceEmbeddings(
    model_name="jhgan/ko-sroberta-multitask",
    encode_kwargs={"normalize_embeddings": True}
)
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)


# --- API 통신 규격 ---
class AskRequest(BaseModel):
    query: str
    vault_path: str | None = None

class AskResponse(BaseModel):
    response: str
    source_file: str
    fallback_used: bool = False
    suggested_title: str | None = None
    suggested_merge_targets: list[str] = [] # 유사도가 높은 기존 메모 추천 목록 3개

class SaveRequest(BaseModel):
    question: str
    answer: str
    source_file: str | None = None # 복습 저장 시 유사도 높은 원본 문서 추적용
    vault_path: str | None = None

class SaveConceptRequest(BaseModel):
    concept_name: str
    content: str
    category: str | None = None
    vault_path: str | None = None

class ReindexRequest(BaseModel):
    vault_path: str | None = None

class ReindexResponse(BaseModel):
    indexed_files: int

class UploadConceptsResponse(BaseModel):
    saved_files: list[str]


# --- 공용 헬퍼 함수 ---

def _resolve_vault(vault_path: str | None) -> Path:
    """요청에 사용자 지정 볼트 경로가 있으면 그 경로를, 없거나 유효하지 않으면 기본 볼트 경로를 반환합니다."""
    if vault_path:
        custom_path = Path(vault_path)
        if custom_path.exists() and custom_path.is_dir():
            return custom_path
    return VAULT_PATH


def _write_concept_file(file_path: Path, concept_name: str, content: str) -> None:
    """개념 노트를 파일로 저장합니다. 이미 존재하면 덮어쓰지 않고 이어붙입니다(Merge)."""
    if file_path.exists():
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(f"\n\n{content}")
    else:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# {concept_name}\n\n{content}")


def _build_or_load_index(current_vault: Path, md_files: list[Path]) -> FAISS:
    """볼트의 마크다운 문서를 청킹하여 FAISS 인덱스를 구축하거나, 최신 상태의 캐시가 있으면 그대로 로드합니다."""
    docs = []
    for file_path in md_files:
        with open(file_path, "r", encoding="utf-8") as f:
            text_content = f.read()
            relative_source = file_path.relative_to(current_vault)
            docs.append(Document(page_content=text_content, metadata={"source": str(relative_source)}))

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
    split_docs = text_splitter.split_documents(docs)

    # Windows 환경의 FAISS C++ 엔진이 한글 경로를 처리할 때 생기는 버그 우회를 위해 파이썬 레벨 직렬화 적용
    vault_hash = hashlib.md5(str(current_vault.resolve()).encode("utf-8")).hexdigest()
    index_file = Path.cwd() / f"faiss_index_{vault_hash}.pkl"

    rebuild_index = True
    if index_file.exists():
        index_time = index_file.stat().st_mtime
        latest_md_time = max((f.stat().st_mtime for f in md_files), default=0)
        if latest_md_time < index_time:
            rebuild_index = False

    if rebuild_index:
        vectorstore = FAISS.from_documents(split_docs, embeddings)
        with open(index_file, "wb") as f:
            f.write(vectorstore.serialize_to_bytes())
    else:
        with open(index_file, "rb") as f:
            serialized_data = f.read()
        vectorstore = FAISS.deserialize_from_bytes(
            serialized_data, embeddings, allow_dangerous_deserialization=True
        )

    return vectorstore


# --- API 엔드포인트 구현 ---

@app.get("/")
async def test_root():
    """
    서버 연결 상태를 테스트하는 간단한 웰컴 API 함수입니다.
    """
    return {"status": "ok", "message": "ObsiRAG API server is running successfully!"}


@app.post("/api/v1/ask", response_model=AskResponse)
async def ask_question(request: AskRequest):
    """
    사용자의 질문에 대해 옵시디언 지식 베이스를 바탕으로 답변과 출처를 제공합니다.
    추가로 질문과 유사도가 높은 기존 메모 목록 3개를 추천하여 손쉽게 병합할 수 있도록 돕습니다.
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
        
    # 사용자 정의 옵시디언 볼트 경로가 있으면 해당 경로 사용, 없으면 기본 경로 사용
    current_vault = _resolve_vault(request.vault_path)

    # 하위 폴더들을 포함하여 모든 md 파일 검색 (glob("**/ *.md") 사용)
    md_files = list(current_vault.glob("**/*.md"))
    # 복습 리스트 및 venv 등 제외 설정
    md_files = [f for f in md_files if f.name != "복습_필요_리스트.md" and "venv" not in f.parts]
    
    fallback_required = False
    answer = ""
    primary_source = "None"
    suggested_title = None
    suggested_merge_targets = []
    
    # 1. 옵시디언 볼트에 문서가 아예 없는 경우 바로 Fallback 처리
    if not md_files:
        fallback_required = True
    else:
        try:
            vectorstore = _build_or_load_index(current_vault, md_files)

            # 병합 추천용: 유사도가 가장 높은 문서 최대 3개 추출 (k=5 범위에서 중복 제거)
            merge_search_docs = vectorstore.as_retriever(search_kwargs={"k": 5}).invoke(request.query)
            seen_sources = set()
            for doc in merge_search_docs:
                src = doc.metadata.get("source")
                if src and src not in seen_sources:
                    seen_sources.add(src)
                    suggested_merge_targets.append(src)
                    if len(suggested_merge_targets) == 3:
                        break
                        
            # Q&A 검색용
            retriever = vectorstore.as_retriever(search_kwargs={"k": 2})
            retrieved_docs = retriever.invoke(request.query)
            
            if not retrieved_docs:
                fallback_required = True
            else:
                primary_source = retrieved_docs[0].metadata.get("source", "알 수 없음")
                context = "\n\n".join([f"[{doc.metadata.get('source')}]:\n{doc.page_content}" for doc in retrieved_docs])
                
                # context 기반 답변 요청 프롬프트
                prompt = f"""당신은 사용자의 옵시디언 지식 베이스를 바탕으로 답변하는 전문가입니다. 아래 제공된 참고 문서(Context)에 기반하여 질문(Question)에 대해 친절하게 한국어로 답변해 주세요.
반드시 제공된 참고 문서(Context) 내용만을 바탕으로 답변해야 합니다. 만약 제공된 참고 문서(Context)에 질문에 대답할 수 있는 정보가 전혀 없거나 매우 부족하다면, 임의로 답변하지 말고 오직 정확히 `[FALLBACK_REQUIRED]` 라고만 출력하십시오.

Context:
{context}

Question: {request.query}

Answer:"""
                
                response = llm.invoke(prompt)
                llm_response = response.content.strip()
                
                if llm_response == "[FALLBACK_REQUIRED]":
                    fallback_required = True
                else:
                    answer = llm_response
                    
        except Exception as e:
            fallback_required = True
            
    # Fallback 처리: 외부 LLM 지식으로 답하고 추천 제목 추출
    if fallback_required:
        try:
            fallback_prompt = f"""당신은 유용한 AI 어시스턴트입니다. 아래 질문에 대해 정확하고 친절하게 한국어로 답변해 주세요.

Question: {request.query}

Answer:"""
            response = llm.invoke(fallback_prompt)
            answer = response.content
            
            # 질문과 답변을 바탕으로 대표 개념 노트 제목 추출
            title_prompt = f"""아래 질문과 답변을 바탕으로, 이 내용을 대표할 수 있는 옵시디언 노트 제목(개념명)을 1개 추출해 주세요. 
기호나 조사를 제외하고 명사 위주의 1~3단어로 작성해야 하며, 오직 추출한 제목(개념명)만 출력하세요. (예: 딥러닝, 벡터 데이터베이스, 파이썬 데코레이터)

질문: {request.query}
답변: {answer[:200]}

제목:"""
            title_response = llm.invoke(title_prompt)
            suggested_title = title_response.content.strip().replace("[", "").replace("]", "")
            suggested_title = re.sub(r'[\\/*?:"<>|]', "", suggested_title)
            
            if not suggested_title or len(suggested_title) > 30:
                suggested_title = "신규_지식_노트"
                
            primary_source = "None (LLM Fallback)"
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Fallback Error: {str(e)}")
            
    return AskResponse(
        response=answer, 
        source_file=primary_source, 
        fallback_used=fallback_required, 
        suggested_title=suggested_title,
        suggested_merge_targets=suggested_merge_targets
    )


@app.post("/api/v1/obsidian/save_concept", status_code=status.HTTP_201_CREATED)
async def save_concept(request: SaveConceptRequest):
    """
    추출된 개념 노트를 카테고리 폴더 또는 루트에 저장합니다.
    """
    if not request.concept_name.strip() or not request.content.strip():
        raise HTTPException(status_code=400, detail="Concept name and content cannot be empty.")

    current_vault = _resolve_vault(request.vault_path)

    # 카테고리 폴더 지정 시 해당 폴더 하위에 저장
    target_dir = current_vault
    if request.category:
        safe_category = re.sub(r'[\\/*?:"<>|]', "", request.category.strip())
        target_dir = current_vault / safe_category
        target_dir.mkdir(parents=True, exist_ok=True)

    file_path = target_dir / f"{request.concept_name}.md"

    # asyncio.Lock으로 쓰기 충돌 방지
    async with file_write_lock:
        try:
            _write_concept_file(file_path, request.concept_name, request.content)
            return {"detail": f"Concept successfully saved to {file_path.name}"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to write to file: {str(e)}")


@app.post("/api/v1/obsidian/save", status_code=status.HTTP_201_CREATED)
async def save_review_note(request: SaveRequest):
    """
    사용자가 이해하기 어려운 개념을 복습 리스트에 추가합니다.
    - 검색을 기반으로 도출된 경우: 유사도가 높은 근거 옵시디언 노트 내부에 직접 기입 및 병합합니다.
    - 검색 근거가 없는 경우: 기본 복습_필요_리스트.md 파일에 추가합니다.
    """
    if not request.question.strip() or not request.answer.strip():
        raise HTTPException(status_code=400, detail="Question and Answer cannot be empty.")

    current_vault = _resolve_vault(request.vault_path)

    # 기본 대상 파일은 복습_필요_리스트.md
    target_file = current_vault / "복습_필요_리스트.md"
    
    # RAG 근거 문서 정보(유사도 높은 파일)가 있고 실제 존재하는 경우 해당 파일로 저장 위치 지정
    is_custom_target = False
    if request.source_file and request.source_file not in ["None", "None (LLM Fallback)", "None (RAG)"]:
        custom_file = current_vault / request.source_file
        if custom_file.exists() and custom_file.is_file():
            target_file = custom_file
            is_custom_target = True
            
    async with file_write_lock:
        try:
            with open(target_file, "a", encoding="utf-8") as f:
                if is_custom_target:
                    f.write(f"\n\n## ⚠️ 복습 필요: {request.question} #복습필요\n")
                    f.write(f"### 💡 AI의 기존 설명:\n{request.answer}\n")
                else:
                    f.write(f"\n\n## ❓ 질문: {request.question} #복습필요\n")
                    f.write(f"### 💡 AI의 기존 설명:\n{request.answer}\n")
                    f.write("-" * 50 + "\n")
            return {"detail": f"Review note successfully saved to {target_file.name}"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to write to file: {str(e)}")


@app.post("/api/v1/obsidian/upload_concepts", response_model=UploadConceptsResponse, status_code=status.HTTP_201_CREATED)
async def upload_concepts(file: UploadFile = File(...), vault_path: str | None = Form(None)):
    """
    PDF 또는 TXT 문서를 업로드받아(청킹) 핵심 개념을 추출하고, 옵시디언 볼트에 마크다운 노트로 저장합니다.
    """
    current_vault = _resolve_vault(vault_path)
    filename = file.filename or "document"
    file_bytes = await file.read()

    # 1. 파일 텍스트 추출 (청킹)
    if filename.lower().endswith(".pdf"):
        try:
            chunks = parse_pdf_to_chunks(BytesIO(file_bytes))
            text = "\n\n".join(chunks)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"PDF 파싱 실패: {str(e)}")
    else:
        # .hwp/.doc 등 OLE 복합 파일 포맷(시그니처 D0 CF 11 E0...)은 아직 지원하지 않음 - 조기 감지
        if file_bytes[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise HTTPException(
                status_code=400,
                detail=f"지원하지 않는 파일 형식입니다: {filename} (.hwp/.doc 등). PDF 또는 TXT로 변환 후 업로드해 주세요."
            )

        # 인코딩이 다양한 한글 텍스트 파일(UTF-8, BOM 포함 UTF-8, CP949/EUC-KR)을 순서대로 시도
        text = None
        for encoding in ("utf-8", "utf-8-sig", "cp949", "euc-kr"):
            try:
                text = file_bytes.decode(encoding)
                break
            except UnicodeDecodeError:
                continue

        if text is None:
            raise HTTPException(status_code=400, detail=f"TXT 파싱 실패: {filename}의 인코딩을 인식할 수 없습니다.")

    if not text.strip():
        raise HTTPException(status_code=400, detail="문서의 텍스트 내용이 비어있습니다.")

    # 2. 개념명 통일을 위해 기존 개념 노트 목록 수집
    existing_concepts = [f.stem for f in current_vault.glob("*.md") if f.name != "복습_필요_리스트.md"]
    existing_concepts_str = ", ".join(existing_concepts) if existing_concepts else "없음"

    # 3. LLM을 통한 개념 추출
    prompt = f"""당신은 지식 구조화 전문가입니다. 아래 입력된 문서에서 핵심 개념들을 추출하여 옵시디언 마크다운 양식으로 작성하세요.

[현재 옵시디언 볼트에 이미 존재하는 기존 개념 노트 목록]:
({existing_concepts_str})

마크다운 출력 및 개념 명명 조건:
1. 중요도가 높은 개념은 개념명 옆에 [#중요] 태그를 붙이고 굵게 표시할 것. (예: **개념명** [#중요])
2. 일반 개념은 [#참고] 태그를 붙일 것.
3. 다른 개념과 연관성이 식별되면 [[연관개념명]] 형태로 내부 링크를 걸 것.
4. **개념명 통합 규칙 (중요)**: 새로 추출하는 개념이 위 기존 목록에 있는 개념명과 의미적으로 동일하거나 매우 유사한 경우, 절대 새로운 이름을 만들지 말고 반드시 기존 목록의 개념명을 동일하게 사용하십시오.

파일 저장 형식 조건:
각 개념을 개별 파일로 분리하기 위해, 각 개념은 반드시 아래 구조로 작성되어야 합니다:
### 개념: [개념명]
[여기에 개념 내용 마크다운...]

입력 문서:
{text}
"""
    try:
        response = llm.invoke(prompt)
        response_text = response.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"개념 추출 실패: {str(e)}")

    # 4. 개념 파싱 및 파일 저장 (기존 노트가 있으면 병합)
    parts = re.split(r'### 개념:', response_text)
    saved_files = []

    async with file_write_lock:
        for part in parts:
            part = part.strip()
            if not part:
                continue
            lines = part.split("\n", 1)
            concept_name = lines[0].replace("[", "").replace("]", "").strip()
            content = lines[1].strip() if len(lines) > 1 else ""

            clean_filename = re.sub(r'[\\/*?:"<>|]', "", concept_name)
            if not clean_filename:
                continue

            file_path = current_vault / f"{clean_filename}.md"
            _write_concept_file(file_path, concept_name, content)
            saved_files.append(f"{clean_filename}.md")

    if not saved_files:
        raise HTTPException(status_code=422, detail="추출된 개념 형식이 올바르지 않아 저장하지 못했습니다.")

    return UploadConceptsResponse(saved_files=saved_files)


@app.post("/api/v1/obsidian/reindex", response_model=ReindexResponse)
async def reindex_vault(request: ReindexRequest):
    """
    옵시디언 볼트의 마크다운 문서를 다시 읽어 FAISS 벡터 인덱스를 최신 상태로 갱신합니다.
    문서 업로드 직후 검색 결과에 바로 반영되도록 하기 위해 사용합니다.
    """
    current_vault = _resolve_vault(request.vault_path)
    md_files = list(current_vault.glob("**/*.md"))
    md_files = [f for f in md_files if f.name != "복습_필요_리스트.md" and "venv" not in f.parts]

    if not md_files:
        return ReindexResponse(indexed_files=0)

    try:
        _build_or_load_index(current_vault, md_files)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reindex Error: {str(e)}")

    return ReindexResponse(indexed_files=len(md_files))
