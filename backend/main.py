import os
import re
import json
import asyncio
import hashlib
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import time
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
from .utils import filter_docs_by_relevance, sanitize_category_path

# 환경 변수 로드
load_dotenv()

if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("OPENAI_API_KEY environment variable is not set.")

app = FastAPI(title="ObsiRAG Backend Server", version="1.0.0")

# CORS 설정 (프론트엔드 호환성 확보)
# 프론트엔드는 쿠키/자격증명을 전혀 사용하지 않으므로 allow_credentials는 False로 둔다.
# (allow_origins="*"과 allow_credentials=True는 브라우저 스펙상 함께 쓸 수 없는 조합이다.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# 검색된 문서를 "관련 학술 논문" 노출 대상으로 볼지 판단하는 최소 연관성 점수(0~1).
# 값이 낮을수록 논문이 더 자주(관련성이 약해도) 노출되고, 높을수록 더 엄격하게 걸러진다.
PAPER_RELEVANCE_THRESHOLD = float(os.getenv("PAPER_RELEVANCE_THRESHOLD", "0.7"))


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
    obsidian_uri: str | None = None

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

class ReindexRequest(BaseModel):
    vault_path: str | None = None

class ReindexResponse(BaseModel):
    indexed_files: int

class UploadConceptsResponse(BaseModel):
    saved_files: list[str]

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


# --- 공용 헬퍼 함수 ---
# (순수 로직인 필터링/경로 새니타이즈는 backend.utils로 분리되어 있다 — 무거운 임포트 없이 단위 테스트 가능)
_filter_docs_by_relevance = filter_docs_by_relevance
_sanitize_category_path = sanitize_category_path


def _resolve_vault(vault_path: str | None) -> Path:
    """요청에 사용자 지정 볼트 경로가 있으면 그 경로를, 없거나 유효하지 않으면 기본 볼트 경로를 반환합니다."""
    if vault_path:
        try:
            custom_path = Path(vault_path.strip())
            custom_path.mkdir(parents=True, exist_ok=True)
            return custom_path
        except Exception as e:
            print(f"Error resolving/creating custom vault path '{vault_path}': {e}")
    return VAULT_PATH



def _write_concept_file(file_path: Path, concept_name: str, content: str) -> None:
    """개념 노트를 파일로 저장합니다. 이미 존재하면 덮어쓰지 않고 이어붙입니다(Merge)."""
    if file_path.exists():
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(f"\n\n{content}")
    else:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# {concept_name}\n\n{content}")


def _index_cache_paths(current_vault: Path) -> tuple[Path, Path]:
    vault_hash = hashlib.md5(str(current_vault.resolve()).encode("utf-8")).hexdigest()
    index_file = Path.cwd() / f"faiss_index_{vault_hash}.pkl"
    manifest_file = Path.cwd() / f"faiss_index_{vault_hash}_manifest.json"
    return index_file, manifest_file


def _invalidate_index_cache(current_vault: Path) -> None:
    """볼트 내용이 바뀐 뒤(개념 저장, 복습 노트 추가 등) 캐시된 FAISS 인덱스를 삭제해 다음 조회 시 재구축을 유도합니다."""
    index_file, manifest_file = _index_cache_paths(current_vault)
    for f in (index_file, manifest_file):
        if f.exists():
            try:
                f.unlink()
            except Exception:
                pass


def _build_or_load_index(current_vault: Path, md_files: list[Path]) -> FAISS:
    """볼트의 마크다운 문서를 청킹하여 FAISS 인덱스를 구축하거나, 최신 상태의 캐시가 있으면 그대로 로드합니다."""
    # Windows 환경의 FAISS C++ 엔진이 한글 경로를 처리할 때 생기는 버그 우회를 위해 파이썬 레벨 직렬화 적용
    index_file, manifest_file = _index_cache_paths(current_vault)

    # 파일 추가/삭제/수정 여부를 모두 감지하기 위해 (상대경로 -> mtime) 전체 매니페스트를 비교한다.
    # mtime 최댓값만 비교하면 파일이 "삭제"된 경우를 감지하지 못하는 문제가 있었다.
    current_manifest = {
        str(f.relative_to(current_vault)): f.stat().st_mtime for f in md_files
    }

    rebuild_index = True
    if index_file.exists() and manifest_file.exists():
        try:
            with open(manifest_file, "r", encoding="utf-8") as mf:
                stored_manifest = json.load(mf)
            rebuild_index = stored_manifest != current_manifest
        except Exception:
            rebuild_index = True

    if rebuild_index:
        docs = []
        for file_path in md_files:
            with open(file_path, "r", encoding="utf-8") as f:
                text_content = f.read()
                relative_source = file_path.relative_to(current_vault)
                docs.append(Document(page_content=text_content, metadata={"source": str(relative_source)}))

        text_splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
        split_docs = text_splitter.split_documents(docs)

        vectorstore = FAISS.from_documents(split_docs, embeddings)
        with open(index_file, "wb") as f:
            f.write(vectorstore.serialize_to_bytes())
        with open(manifest_file, "w", encoding="utf-8") as mf:
            json.dump(current_manifest, mf)
    else:
        with open(index_file, "rb") as f:
            serialized_data = f.read()
        vectorstore = FAISS.deserialize_from_bytes(
            serialized_data, embeddings, allow_dangerous_deserialization=True
        )

    return vectorstore


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

    # 사용자 정의 옵시디언 볼트 경로가 있으면 해당 경로 사용, 없으면 기본 경로 사용
    current_vault = _resolve_vault(request.vault_path)

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

            retrieved_docs_with_scores = vectorstore.similarity_search_with_relevance_scores(request.query, k=4)
            retrieved_docs = [doc for doc, _score in retrieved_docs_with_scores]

            if not retrieved_docs:
                fallback_required = True
            else:
                primary_source = retrieved_docs[0].metadata.get("source", "알 수 없음")
                context = "\n\n".join([f"[{doc.metadata.get('source')}]:\n{doc.page_content}" for doc in retrieved_docs])

                # 지식 노트 내용에서 기존에 저장된 학술 논문 출처 패턴 파싱 (전체 파일 단위)
                # 질문과의 연관성 점수가 낮은 문서는 관련 없는 논문이 계속 노출되는 문제를 막기 위해 제외한다.
                relevant_docs_for_papers = _filter_docs_by_relevance(retrieved_docs_with_scores, PAPER_RELEVANCE_THRESHOLD)
                seen_files_for_papers = set()
                for doc in relevant_docs_for_papers:
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

    obsidian_uri = None
    if not fallback_required and primary_source != "Unknown" and primary_source != "None (LLM Fallback)":
        try:
            src_path = Path(primary_source)
            if src_path.is_absolute():
                rel_path = src_path.relative_to(current_vault)
            else:
                rel_path = src_path
            vault_name = current_vault.name
            from urllib.parse import quote
            safe_rel_path = quote(str(rel_path).replace("\\", "/"))
            safe_vault_name = quote(vault_name)
            obsidian_uri = f"obsidian://open?vault={safe_vault_name}&file={safe_rel_path}"
        except Exception as ue:
            print(f"Failed to generate obsidian_uri: {ue}")

    return AskResponse(
        response=answer,
        source_file=primary_source,
        fallback_used=fallback_required,
        suggested_title=suggested_title,
        suggested_merge_targets=suggested_merge_targets,
        saved_papers=saved_papers,
        obsidian_uri=obsidian_uri
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
        # 아카이브 API가 차단되었거나 타임아웃된 경우, 사용자 경험을 위해 LLM의 자체 지식을 기반으로 논문 추천 수행 (Fallback)
        try:
            print(f"[ArXiv Search] API failed or rate limited for query '{english_query}'. Falling back to LLM recommendations...")
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
            print(f"LLM paper fallback failed: {ge}")
            return []

    try:
        # LLM을 활용하여 영문 초록들을 한글 요약본으로 일괄 번역/요약 (배치 처리)
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
    current_vault = _resolve_vault(request.vault_path)

    md_files = list(current_vault.glob("**/*.md"))
    md_files = [f for f in md_files if f.name != "복습_필요_리스트.md" and "venv" not in f.parts]

    if not md_files:
        return []

    try:
        vectorstore = _build_or_load_index(current_vault, md_files)
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

    current_vault = _resolve_vault(request.vault_path)
    clean_filename = re.sub(r'[\\/*?:"<>|]', "", request.concept_name.strip())
    if not clean_filename:
        raise HTTPException(status_code=400, detail="Concept name contains only illegal filename characters.")

    # 1. 기존에 볼트 내 다른 하위 폴더에 동일한 파일이 존재하는지 검사
    existing_file = None
    for p in current_vault.rglob("*.md"):
        if "venv" in p.parts or p.name.startswith(".") or p.name == "복습_필요_리스트.md":
            continue
        if p.stem == clean_filename:
            existing_file = p
            break

    if existing_file:
        file_path = existing_file
    else:
        # 2. 새로운 개념 노트 생성 시 카테고리 지정
        target_dir = current_vault
        if request.category:
            target_dir = _sanitize_category_path(request.category, current_vault)
            target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / f"{clean_filename}.md"

    # asyncio.Lock으로 쓰기 충돌 방지
    async with file_write_lock:
        try:
            _write_concept_file(file_path, request.concept_name, request.content)
            _invalidate_index_cache(current_vault)
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

    current_vault = _resolve_vault(request.vault_path)

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

            _invalidate_index_cache(current_vault)
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

    # 2. 개념명 통일 및 카테고리 매칭을 위해 기존 개념 노트 및 폴더 목록 수집 (재귀 스캔)
    existing_concepts = []
    existing_dirs = set()
    
    for p in current_vault.rglob("*"):
        if "venv" in p.parts or p.name.startswith("."):
            continue
        if p.is_file() and p.suffix == ".md" and p.name != "복습_필요_리스트.md":
            existing_concepts.append(p.stem)
            rel_dir = p.parent.relative_to(current_vault)
            if str(rel_dir) != ".":
                existing_dirs.add(str(rel_dir).replace("\\", "/"))
        elif p.is_dir():
            rel_dir = p.relative_to(current_vault)
            if str(rel_dir) != ".":
                existing_dirs.add(str(rel_dir).replace("\\", "/"))

    existing_concepts_str = ", ".join(set(existing_concepts)) if existing_concepts else "없음"
    existing_dirs_str = ", ".join(sorted(list(existing_dirs))) if existing_dirs else "없음 (루트 저장)"

    # 3. LLM을 통한 개념 추출
    prompt = f"""당신은 지식 구조화 전문가입니다. 아래 입력된 문서에서 핵심 개념들을 추출하여 옵시디언 마크다운 양식으로 작성하세요.

[현재 옵시디언 볼트에 이미 존재하는 기존 개념 노트 목록]:
({existing_concepts_str})

[현재 옵시디언 볼트에 이미 존재하는 기존 폴더(카테고리) 목록]:
({existing_dirs_str})

마크다운 출력 및 개념 명명 조건:
1. 중요도가 높은 개념은 개념명 옆에 [#중요] 태그를 붙이고 굵게 표시할 것. (예: **개념명** [#중요])
2. 일반 개념은 [#참고] 태그를 붙일 것.
3. 다른 개념과 연관성이 식별되면 [[연관개념명]] 형태로 내부 링크를 걸 것.
4. **개념명 통합 규칙 (최우선)**:
   - 새로 추출하는 개념이 기존 개념 노트 목록에 있는 개념과 의미상 동일하거나 매우 유사한 경우(예: '배치 정규화'와 'Batch Normalization', '합성곱 신경망'과 'CNN', '딥러닝'과 'DL'), 절대 새로운 이름을 작성하지 말고, **반드시 기존에 존재하는 개념명을 토씨 하나 틀리지 않고 동일하게 사용하여 덮어쓰기/병합되도록 하십시오.**
   - 기존 목록에 없더라도, 이번 문서에서 추출되는 개념들 중 의미적으로 동일한 개념(예: 동의어, 한글/영문 약어 혼용)이 있다면 한쪽(가급적 한글 완칭)으로 명칭을 완전히 통일하고 본문 내에 함께 설명하십시오. (예: '딥러닝'과 'DL'을 각각 분리하여 두 개의 개념으로 추출하지 말고, '딥러닝' 하나로만 추출한 후 본문에 'DL(Deep Learning)이라고도 한다'라고 기술하십시오.)

옵시디언 계층적 구조 설정 조건 (필수):
1. **노트 내부 계층 연결**: 개념 노트의 맨 상단에 해당 개념의 상위(부모) 개념과 하위(자식) 개념을 분석하여 내부 링크로 연결하십시오.
   - 예시:
     - 상위 개념: [[상위개념명]]
     - 하위 개념: [[하위개념1]], [[하위개념2]] (없으면 생략 가능)
2. **계층형 태그 추가**: 추천 폴더 경로에 맞춰 옵시디언의 계층형 태그를 마크다운 내용에 포함하십시오.
   - 예시: 카테고리가 `인공지능/딥러닝` 이라면 노트 내용 내에 `#인공지능/딥러닝` 형식의 계층형 태그를 추가하십시오.
3. **노트 본문 계층화**: 단순히 텍스트를 길게 서술하지 말고, 제목 헤더(`##`, `###`)를 사용하여 개념 정의, 특징, 적용 사례 등을 계층적으로 분할하여 마크다운을 작성하십시오.

파일 저장 형식 조건:
각 개념을 개별 파일로 분리하고 올바른 카테고리에 저장하기 위해, 각 개념은 반드시 아래의 명확한 구조로 작성되어야 합니다. 다른 불필요한 설명은 포함하지 마십시오:
### 개념: [개념명]
### 카테고리: [추천 폴더 경로]
[여기에 개념 내용 마크다운...]

* [추천 폴더 경로] 설정 규칙 (매우 중요):
  - 각 개념의 도메인 분야(상위 분류)를 분석하여 계층 구조를 갖춘 카테고리 폴더 경로를 지정해 주십시오. 가급적 '대분류/중분류/소분류' 등 깊이 있는 계층 경로로 설계해 주십시오. (예: "인공지능/딥러닝/최적화", "컴퓨터과학/알고리즘/정렬", "웹개발/백엔드/데이터베이스")
  - 위 [기존 폴더 목록]에 해당 개념이 속할 수 있는 적합한 폴더가 있다면 해당 경로를 우선적으로 그대로 쓰십시오.
  - 만약 도저히 상위 카테고리를 분류하기 어렵거나 루트에 바로 저장해야 하는 일반 개념인 경우에만 "루트"라고 작성해 주십시오.

입력 문서:
{text}
"""
    try:
        response = llm.invoke(prompt)
        response_text = get_clean_string_content(response.content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"개념 추출 실패: {str(e)}")

    # 4. 개념 파싱 및 파일 저장 (기존 노트가 있으면 병합)
    parts = re.split(r'### 개념:', response_text)
    saved_files = []

    # 기존 옵시디언 볼트 내 마크다운 파일 맵 빌드 (공백 제거, 소문자화하여 동의어 및 포맷 불일치 대응)
    existing_file_map = {}
    for p in current_vault.rglob("*.md"):
        if "venv" in p.parts or p.name.startswith(".") or p.name == "복습_필요_리스트.md":
            continue
        normalized_name = p.stem.lower().replace(" ", "")
        if normalized_name not in existing_file_map:
            existing_file_map[normalized_name] = p

    async with file_write_lock:
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            lines = part.split("\n", 1)
            concept_name = lines[0].replace("[", "").replace("]", "").strip()
            remaining = lines[1].strip() if len(lines) > 1 else ""
            
            category_path = ""
            content = remaining
            cat_match = re.match(r'^###\s*카테고리\s*:\s*(.*?)\n(.*)$', remaining, re.DOTALL)
            if cat_match:
                category_raw = cat_match.group(1).replace("[", "").replace("]", "").strip()
                if category_raw and category_raw != "루트":
                    category_path = category_raw
                content = cat_match.group(2).strip()
            
            clean_filename = re.sub(r'[\\/*?:"<>|]', "", concept_name)
            if not clean_filename:
                continue

            normalized_new_name = clean_filename.lower().replace(" ", "")

            # 기존에 동일한(또는 유사한) 이름의 파일이 존재하는지 검사 (대소문자/공백 무시 비교)
            if normalized_new_name in existing_file_map:
                file_path = existing_file_map[normalized_new_name]
                # 기존 파일이 있다면 파일 이름의 철자와 대소문자를 기존 파일 기준으로 통일
                concept_name = file_path.stem
            else:
                target_dir = current_vault
                if category_path:
                    target_dir = _sanitize_category_path(category_path, current_vault)
                    target_dir.mkdir(parents=True, exist_ok=True)
                file_path = target_dir / f"{clean_filename}.md"
                # 실시간으로 추가하여 이번 배치 업로드 도중 발생하는 중복도 방지
                existing_file_map[normalized_new_name] = file_path

            _write_concept_file(file_path, concept_name, content)
            
            relative_saved = file_path.relative_to(current_vault)
            saved_files.append(str(relative_saved).replace("\\", "/"))

        if saved_files:
            _invalidate_index_cache(current_vault)

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


@app.post("/api/v1/obsidian/folders", response_model=list[str])
async def get_folders(request: ReindexRequest):
    """
    옵시디언 볼트의 전체 폴더(카테고리) 목록을 재귀적으로 스캔하여 반환합니다.
    """
    current_vault = _resolve_vault(request.vault_path)
    folders = set()
    try:
        for p in current_vault.rglob("*"):
            if "venv" in p.parts or p.name.startswith("."):
                continue
            if p.is_dir():
                rel_dir = p.relative_to(current_vault)
                if str(rel_dir) != ".":
                    folders.add(str(rel_dir).replace("\\", "/"))
        return sorted(list(folders))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Folders listing failed: {str(e)}")


@app.post("/api/v1/obsidian/concepts", response_model=list[str])
async def get_concepts(request: ReindexRequest):
    """
    옵시디언 볼트의 전체 개념(마크다운 파일 stem) 목록을 재귀적으로 스캔하여 반환합니다.
    """
    current_vault = _resolve_vault(request.vault_path)
    concepts = set()
    try:
        for p in current_vault.rglob("*.md"):
            if "venv" in p.parts or p.name.startswith(".") or p.name == "복습_필요_리스트.md":
                continue
            concepts.add(p.stem)
        return sorted(list(concepts))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Concepts listing failed: {str(e)}")
