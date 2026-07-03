import os
import re
import json
import asyncio
import hashlib
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import time
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
env_vault_path = os.getenv("OBSIDIAN_VAULT_PATH")
if env_vault_path:
    VAULT_PATH = Path(env_vault_path)
else:
    VAULT_PATH = Path.cwd() / "my_obsidian_vault"
VAULT_PATH.mkdir(parents=True, exist_ok=True)

# 파일 쓰기 충돌 방지를 위한 Lock 객체
file_write_lock = asyncio.Lock()

# 임베딩 모델 및 LLM 초기화
embeddings = HuggingFaceEmbeddings(
    model_name="jhgan/ko-sroberta-multitask",
    encode_kwargs={"normalize_embeddings": True}
)
llm = ChatGoogleGenerativeAI(model="gemini-3.5-flash", temperature=0)


# --- API 헬퍼 함수: 프리뷰 모델의 block-list 반환 호환성 확보 ---
def get_clean_string_content(content) -> str:
    """
    일부 프리뷰 모델(gemini-3-flash-preview 등)에서 response.content가 문자열 대신 
    블록 구조의 리스트나 사전 형태의 리스트로 반환될 수 있는 호환성 문제를 처리하기 위해,
    내용을 안전하게 순수 문자열로 추출 및 정제해 주는 헬퍼 함수입니다.
    """
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and "text" in part:
                parts.append(part["text"])
        return "".join(parts)
    return str(content)


# --- API 통신 규격 ---
class AskRequest(BaseModel):
    query: str
    vault_path: str | None = None

class AskResponse(BaseModel):
    response: str
    source_file: str
    fallback_used: bool = False
    suggested_title: str | None = None
    suggested_merge_targets: list[str] = []
    saved_papers: list[dict] = []

class SaveRequest(BaseModel):
    question: str
    answer: str
    source_file: str | None = None
    vault_path: str | None = None

class SaveConceptRequest(BaseModel):
    concept_name: str
    content: str
    category: str | None = None
    vault_path: str | None = None

class PaperSearchRequest(BaseModel):
    query: str

class PaperInfo(BaseModel):
    title: str
    authors: str
    summary: str
    link: str

class SimilarDocsRequest(BaseModel):
    query: str
    vault_path: str | None = None


# --- ArXiv API 연동 헬퍼 함수 ---
def search_arxiv_papers(query: str, max_results: int = 4) -> list:
    """
    ArXiv API를 호출하여 검색어와 관련된 학술 논문 목록을 추출합니다.
    자주 생기는 429 Rate Limit(호출 초과) 에러에 대비하여 대기 후 재시도(Retry) 메커니즘을 포함합니다.
    """
    encoded_query = urllib.parse.quote(query)
    url = f"http://export.arxiv.org/api/query?search_query=all:{encoded_query}&start=0&max_results={max_results}"
    
    xml_data = None
    # 최대 3회 재시도 (재시도 간 격차 부여)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=12) as response:
                xml_data = response.read()
            break  # 성공 시 루프 탈출
        except urllib.error.HTTPError as he:
            if he.code in [403, 429]:
                # 호출 속도 제한에 걸린 경우 3초 대기 후 재시도
                print(f"[ArXiv API] Rate limited (code {he.code}). Waiting 3.0s before retry (attempt {attempt+1}/3)...")
                time.sleep(3.0)
                continue
            raise he
        except Exception as e:
            if attempt < 2:
                time.sleep(2.0)
                continue
            print(f"ArXiv Connection Error after retries: {e}")
            return []
            
    if not xml_data:
        return []
        
    try:
        root = ET.fromstring(xml_data)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        
        papers = []
        for entry in root.findall('atom:entry', ns):
            title_node = entry.find('atom:title', ns)
            title = title_node.text.strip().replace("\n", " ") if title_node is not None else "Unknown Title"
            
            id_node = entry.find('atom:id', ns)
            link = id_node.text.strip() if id_node is not None else ""
            
            authors = []
            for author_node in entry.findall('atom:author', ns):
                name_node = author_node.find('atom:name', ns)
                if name_node is not None:
                    authors.append(name_node.text.strip())
            authors_str = ", ".join(authors) if authors else "Unknown Authors"
            
            summary_node = entry.find('atom:summary', ns)
            abstract = summary_node.text.strip().replace("\n", " ") if summary_node is not None else ""
            
            papers.append({
                "title": title,
                "authors": authors_str,
                "abstract": abstract,
                "link": link
            })
        return papers
    except Exception as e:
        print(f"ArXiv XML Parsing Error: {e}")
        return []


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
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
        
    current_vault = VAULT_PATH
    if request.vault_path:
        custom_path = Path(request.vault_path)
        if custom_path.exists() and custom_path.is_dir():
            current_vault = custom_path
            
    md_files = list(current_vault.glob("**/*.md"))
    md_files = [f for f in md_files if f.name != "복습_필요_리스트.md" and "venv" not in f.parts]
    
    fallback_required = False
    answer = ""
    primary_source = "None"
    suggested_title = None
    suggested_merge_targets = []
    saved_papers = []
    
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
                    
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
            split_docs = text_splitter.split_documents(docs)
            
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
                
            merge_search_docs = vectorstore.as_retriever(search_kwargs={"k": 5}).invoke(request.query)
            seen_sources = set()
            for doc in merge_search_docs:
                src = doc.metadata.get("source")
                if src and src not in seen_sources:
                    seen_sources.add(src)
                    suggested_merge_targets.append(src)
                    if len(suggested_merge_targets) == 3:
                        break
                        
            retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
            retrieved_docs = retriever.invoke(request.query)
            
            if not retrieved_docs:
                fallback_required = True
            else:
                primary_source = retrieved_docs[0].metadata.get("source", "알 수 없음")
                context = "\n\n".join([f"[{doc.metadata.get('source')}]:\n{doc.page_content}" for doc in retrieved_docs])
                
                # 지식 노트 내용에서 기존에 저장된 학술 논문 출처 패턴 파싱 (전체 파일 단위)
                seen_files_for_papers = set()
                for doc in retrieved_docs:
                    src = doc.metadata.get("source")
                    if src and src not in seen_files_for_papers:
                        seen_files_for_papers.add(src)
                        try:
                            full_file_path = current_vault / src
                            if full_file_path.exists():
                                with open(full_file_path, "r", encoding="utf-8") as rf:
                                    file_text = rf.read()
                                matches = re.finditer(
                                    r'### 📚 관련 학술 논문 출처:\s*(.*?)\n-\s*\*\*저자\*\*:\s*(.*?)\n-\s*\*\*링크\*\*:\s*(.*?)\n-\s*\*\*AI 번역 요약\*\*:\s*(.*?)(?=\n\n|\n##|\n#|\Z)',
                                    file_text,
                                    re.DOTALL
                                )
                                for match in matches:
                                    title = match.group(1).strip()
                                    authors = match.group(2).strip()
                                    link = match.group(3).strip()
                                    summary = match.group(4).strip()
                                    saved_papers.append({
                                        "title": title,
                                        "authors": authors,
                                        "link": link,
                                        "summary": summary,
                                        "source_file": src
                                    })
                        except Exception as pe:
                            print(f"Error parsing papers from file: {pe}")
                
                prompt = f"""당신은 사용자의 옵시디언 지식 베이스를 바탕으로 답변하는 전문가입니다. 
제공된 참고 문서(Context)를 최우선으로 사용하여 질문(Question)에 대해 친절하게 한국어로 답변해 주세요. 
특히 참고 문서에 논문 정보(제목, 저자, 요약)가 기재되어 있다면, 답변 시 해당 논문 정보를 상세히 언급하고 함께 설명해 주어야 합니다.

만약 제공된 참고 문서(Context)가 질문과 전혀 무관하거나 관련 내용이 아예 없다면, 오직 정확히 `[FALLBACK_REQUIRED]` 라고만 출력하십시오.

Context:
{context}

Question: {request.query}

Answer:"""
                
                response = llm.invoke(prompt)
                llm_response = get_clean_string_content(response.content).strip()
                
                if llm_response == "[FALLBACK_REQUIRED]":
                    fallback_required = True
                else:
                    answer = llm_response
                    
        except Exception as e:
            fallback_required = True
            
    if fallback_required:
        try:
            fallback_prompt = f"""당신은 유용한 AI 어시스턴트입니다. 아래 질문에 대해 정확하고 친절하게 한국어로 답변해 주세요.

Question: {request.query}

Answer:"""
            response = llm.invoke(fallback_prompt)
            answer = get_clean_string_content(response.content)
            
            title_prompt = f"""아래 질문과 답변을 바탕으로, 이 내용을 대표할 수 있는 옵시디언 노트 제목(개념명)을 1개 추출해 주세요. 
기호나 조사를 제외하고 명사 위주의 1~3단어로 작성해야 하며, 오직 추출한 제목(개념명)만 출력하세요. (예: 딥러닝, 벡터 데이터베이스, 파이썬 데코레이터)

질문: {request.query}
답변: {answer[:200]}

제목:"""
            title_response = llm.invoke(title_prompt)
            suggested_title = get_clean_string_content(title_response.content).strip().replace("[", "").replace("]", "")
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
        suggested_merge_targets=suggested_merge_targets,
        saved_papers=saved_papers
    )


@app.post("/api/v1/papers/search", response_model=list[PaperInfo])
async def search_papers(request: PaperSearchRequest):
    """
    ArXiv API를 호출해 검색어와 관련된 상위 4개 논문을 검색하고 한글로 요약하여 반환합니다.
    한국어 질의어인 경우 영어 검색어로 변환을 선행하여 검색 품질과 API 연동 안정성을 극대화합니다.
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
        
    # 1. 한국어 검색어를 ArXiv 학술 검색용 영어 키워드로 자동 추출 및 번역
    english_query = request.query
    try:
        translation_prompt = f"""아래 질문(검색어)을 바탕으로, 아카이브(ArXiv) 학술 논문 검색에 사용할 가장 적절한 영어 검색 키워드(단어 또는 짧은 구문)를 1개만 추출/번역해 주세요.
출력할 때는 따옴표나 특수 기호 없이 오직 영어 키워드만 한 줄로 출력하세요. (예: "딥러닝" -> "deep learning", "RAG 단계" -> "Retrieval-Augmented Generation")

질문: {request.query}

키워드:"""
        translation_response = llm.invoke(translation_prompt)
        extracted_kw = get_clean_string_content(translation_response.content).strip().replace('"', '').replace("'", "")
        if extracted_kw and len(extracted_kw) < 50:
            english_query = extracted_kw
            print(f"[ArXiv Search] Translated query '{request.query}' -> '{english_query}'")
    except Exception as te:
        print(f"Keyword translation failed: {te}")
        
    # 2. ArXiv 논문 수집 (영어 키워드로 검색하여 429 차단 우회 및 대기 해소)
    papers = search_arxiv_papers(english_query, max_results=4)
    
    if not papers:
        # 아카이브 API가 차단되었거나 타임아웃된 경우, 사용자 경험을 위해 Gemini의 자체 지식을 기반으로 논문 추천 수행 (Fallback)
        try:
            print(f"[ArXiv Search] API failed or rate limited for query '{english_query}'. Falling back to Gemini recommendations...")
            fallback_prompt = f"""당신은 유능한 컴퓨터 과학 및 인공지능 학술 연구원입니다. 
다음 검색 키워드(영문)와 밀접하게 관련이 있는 실제 존재하는 대표적인 학술 논문 4개를 추천해 주세요:
키워드: {english_query}

반드시 실제로 학계에 발표된 유명하고 공신력 있는 논문이어야 하며, 존재하지 않는 허구의 논문을 지어내지 마십시오.
결과는 오직 아래의 JSON 배열 형식으로만 출력해야 합니다. 다른 서론이나 설명은 일절 배제해 주세요.

[
  {{
    "title": "논문 영문 제목",
    "authors": "주요 저자 이름들",
    "summary": "논문의 핵심 내용 및 기여점에 대한 한국어 요약 (2~3문장)",
    "link": "해당 논문의 실제 ArXiv 주소 또는 공식 URL"
  }}
]

JSON:"""
            response = llm.invoke(fallback_prompt)
            content_str = get_clean_string_content(response.content).strip()
            
            # 마크다운 코드 블록이 포함되어 있으면 제거
            content_str = re.sub(r'^```json\s*', '', content_str, flags=re.IGNORECASE)
            content_str = re.sub(r'\s*```$', '', content_str, flags=re.IGNORECASE)
            
            papers_data = json.loads(content_str)
            paper_infos = []
            for p in papers_data[:4]:
                paper_infos.append(PaperInfo(
                    title=p.get("title", "Unknown Title"),
                    authors=p.get("authors", "Unknown Authors"),
                    summary=p.get("summary", ""),
                    link=p.get("link", "")
                ))
            return paper_infos
        except Exception as ge:
            print(f"Gemini paper fallback failed: {ge}")
            return []
        
    try:
        # Gemini를 활용하여 영문 초록들을 한글 요약본으로 일괄 번역/요약 (배치 처리)
        batch_prompt = """당신은 학술 논문 요약 전문가입니다. 아래 제시된 영문 논문 초록(Abstract)들을 읽고,
각 논문의 주요 핵심 기여점과 결과에 대해 비전문가도 이해할 수 있는 자연스러운 한글로 2~3문장 내외로 번역 및 요약해 주세요.
부연 설명이나 메타 정보 없이 오직 번호 순서에 맞춰 요약본 텍스트만 출력해 주세요. (예: 1. [요약]\n2. [요약] ...)

"""
        for idx, p in enumerate(papers, 1):
            batch_prompt += f"[{idx}] 제목: {p['title']}\n초록: {p['abstract'][:800]}\n\n"
            
        response = llm.invoke(batch_prompt)
        summaries_raw = get_clean_string_content(response.content).strip().split("\n")
        
        summaries = {}
        current_idx = 1
        for line in summaries_raw:
            line_str = line.strip()
            match = re.match(r'^(?:\[?(\d+)\]?[\s\.)\-]+|(\d+)[\s\.)\-]+)(.*)$', line_str)
            if match:
                idx = int(match.group(1) or match.group(2))
                content = match.group(3).strip()
                summaries[idx] = content
                current_idx = idx
            elif line_str and current_idx in summaries:
                summaries[current_idx] += " " + line_str
                
        paper_infos = []
        for idx, p in enumerate(papers, 1):
            summary = summaries.get(idx, p['abstract'][:200] + "...")
            paper_infos.append(PaperInfo(
                title=p['title'],
                authors=p['authors'],
                summary=summary,
                link=p['link']
            ))
        return paper_infos
    except Exception as e:
        return [
            PaperInfo(
                title=p['title'],
                authors=p['authors'],
                summary=p['abstract'][:200] + "...",
                link=p['link']
            ) for p in papers
        ]


@app.post("/api/v1/obsidian/similar_docs", response_model=list[str])
async def get_similar_docs(request: SimilarDocsRequest):
    """
    제시된 텍스트(예: 논문 제목)와 벡터 유사도가 가장 높은 옵시디언 문서 상위 5개의 상대 경로 목록을 반환합니다.
    """
    current_vault = VAULT_PATH
    if request.vault_path:
        custom_path = Path(request.vault_path)
        if custom_path.exists() and custom_path.is_dir():
            current_vault = custom_path
            
    md_files = list(current_vault.glob("**/*.md"))
    md_files = [f for f in md_files if f.name != "복습_필요_리스트.md" and "venv" not in f.parts]
    
    if not md_files:
        return []
        
    try:
        vault_hash = hashlib.md5(str(current_vault.resolve()).encode("utf-8")).hexdigest()
        INDEX_FILE = Path.cwd() / f"faiss_index_{vault_hash}.pkl"
        
        if not INDEX_FILE.exists():
            docs = []
            for file_path in md_files:
                with open(file_path, "r", encoding="utf-8") as f:
                    text_content = f.read()
                    relative_source = file_path.relative_to(current_vault)
                    docs.append(Document(page_content=text_content, metadata={"source": str(relative_source)}))
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
            split_docs = text_splitter.split_documents(docs)
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
            
        retrieved = vectorstore.as_retriever(search_kwargs={"k": 10}).invoke(request.query)
        
        similar_sources = []
        seen = set()
        for doc in retrieved:
            src = doc.metadata.get("source")
            if src and src not in seen:
                seen.add(src)
                similar_sources.append(src)
                if len(similar_sources) == 5:
                    break
        return similar_sources
    except Exception as e:
        print(f"Error finding similar docs: {e}")
        return [str(f.relative_to(current_vault)) for f in md_files[:5]]


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
            
    target_dir = current_vault
    if request.category:
        safe_category = re.sub(r'[\\*?:"<>|]', "", request.category.strip())
        target_dir = current_vault / safe_category
        target_dir.mkdir(parents=True, exist_ok=True)
        
    file_path = target_dir / f"{request.concept_name}.md"
    
    async with file_write_lock:
        try:
            if file_path.exists():
                with open(file_path, "a", encoding="utf-8") as f:
                    f.write(f"\n\n{request.content}")
            else:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(f"# {request.concept_name}\n\n{request.content}")
                    
            # 인덱스 파일 캐시 삭제하여 다음 조회 시 무조건 최신 데이터로 인덱스 재빌드 유도
            vault_hash = hashlib.md5(str(current_vault.resolve()).encode("utf-8")).hexdigest()
            INDEX_FILE = Path.cwd() / f"faiss_index_{vault_hash}.pkl"
            if INDEX_FILE.exists():
                try:
                    INDEX_FILE.unlink()
                except Exception:
                    pass
                    
            return {"detail": f"Concept successfully saved to {file_path.name}"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to write to file: {str(e)}")


@app.post("/api/v1/obsidian/save", status_code=status.HTTP_201_CREATED)
async def save_review_note(request: SaveRequest):
    """
    사용자가 이해하기 어려운 개념을 복습 리스트에 추가합니다.
    """
    if not request.question.strip() or not request.answer.strip():
        raise HTTPException(status_code=400, detail="Question and Answer cannot be empty.")
        
    current_vault = VAULT_PATH
    if request.vault_path:
        custom_path = Path(request.vault_path)
        if custom_path.exists() and custom_path.is_dir():
            current_vault = custom_path
            
    target_file = current_vault / "복습_필요_리스트.md"
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
                    
            # 인덱스 파일 캐시 삭제하여 다음 조회 시 무조건 최신 데이터로 인덱스 재빌드 유도
            vault_hash = hashlib.md5(str(current_vault.resolve()).encode("utf-8")).hexdigest()
            INDEX_FILE = Path.cwd() / f"faiss_index_{vault_hash}.pkl"
            if INDEX_FILE.exists():
                try:
                    INDEX_FILE.unlink()
                except Exception:
                    pass
                    
            return {"detail": f"Review note successfully saved to {target_file.name}"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to write to file: {str(e)}")
