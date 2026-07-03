import os
import re
import asyncio
import hashlib
from pathlib import Path
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_google_genai import ChatGoogleGenerativeAI

# 환경 변수 로드
load_dotenv()

if not os.getenv("GOOGLE_API_KEY"):
    raise ValueError("GOOGLE_API_KEY environment variable is not set.")

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
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=0)


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
    current_vault = VAULT_PATH
    if request.vault_path:
        custom_path = Path(request.vault_path)
        if custom_path.exists() and custom_path.is_dir():
            current_vault = custom_path
            
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
            docs = []
            for file_path in md_files:
                with open(file_path, "r", encoding="utf-8") as f:
                    text_content = f.read()
                    relative_source = file_path.relative_to(current_vault)
                    docs.append(Document(page_content=text_content, metadata={"source": str(relative_source)}))
                    
            # 텍스트 분할
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
            split_docs = text_splitter.split_documents(docs)
            
            # FAISS 벡터화 및 로컬 인덱스 로드/저장 최적화
            # Windows 환경의 FAISS C++ 엔진이 한글 경로를 처리할 때 생기는 버그 우회를 위해 파이썬 레벨 직렬화 적용
            vault_hash = hashlib.md5(str(current_vault.resolve()).encode("utf-8")).hexdigest()
            INDEX_FILE = Path.cwd() / f"faiss_index_{vault_hash}.pkl"
            rebuild_index = True
            
            if INDEX_FILE.exists():
                index_time = INDEX_FILE.stat().st_mtime
                latest_md_time = max((f.stat().st_mtime for f in md_files), default=0)
                if latest_md_time < index_time:
                    rebuild_index = False
                        
            if rebuild_index:
                vectorstore = FAISS.from_documents(split_docs, embeddings)
                serialized_data = vectorstore.serialize_to_bytes()
                with open(INDEX_FILE, "wb") as f:
                    f.write(serialized_data)
            else:
                with open(INDEX_FILE, "rb") as f:
                    serialized_data = f.read()
                vectorstore = FAISS.deserialize_from_bytes(
                    serialized_data, 
                    embeddings, 
                    allow_dangerous_deserialization=True
                )
                
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
        
    current_vault = VAULT_PATH
    if request.vault_path:
        custom_path = Path(request.vault_path)
        if custom_path.exists() and custom_path.is_dir():
            current_vault = custom_path
            
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
            if file_path.exists():
                with open(file_path, "a", encoding="utf-8") as f:
                    f.write(f"\n\n{request.content}")
            else:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(f"# {request.concept_name}\n\n{request.content}")
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
        
    current_vault = VAULT_PATH
    if request.vault_path:
        custom_path = Path(request.vault_path)
        if custom_path.exists() and custom_path.is_dir():
            current_vault = custom_path
            
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
