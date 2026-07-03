import os
import re
from pathlib import Path
from dotenv import load_dotenv
import streamlit as st
from pypdf import PdfReader

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_google_genai import ChatGoogleGenerativeAI

# 0. API 키 관리 및 환경변수 로드
load_dotenv()

st.set_page_config(page_title="ObsiRAG: 옵시디언 연동형 RAG", page_icon="📋", layout="wide")

# API Key 검증
if not os.getenv("GOOGLE_API_KEY"):
    st.title("📋 ObsiRAG 시스템 설정")
    st.warning("🔑 Google Gemini API Key가 설정되지 않았습니다.")
    st.markdown("API Key는 [Google AI Studio](https://aistudio.google.com/)에서 무료로 발급받으실 수 있습니다.")
    api_key_input = st.text_input("Gemini API Key를 입력하세요", type="password")
    if st.button("API Key 저장"):
        if api_key_input:
            with open(".env", "w", encoding="utf-8") as f:
                f.write(f"GOOGLE_API_KEY={api_key_input}\n")
            st.success("✅ .env 파일에 API Key가 저장되었습니다! 새로고침하여 시작해 주세요.")
            st.rerun()
        else:
            st.error("API Key를 입력해 주세요.")
    st.stop()

# 1. 경로 관리 및 초기화 (pathlib.Path 사용)
st.sidebar.title("📁 옵시디언 경로 설정")
default_vault_path = str(Path.cwd() / "my_obsidian_vault")
vault_path_str = st.sidebar.text_input("옵시디언 볼트(Vault) 절대 경로", default_vault_path)
vault_path = Path(vault_path_str)

# 폴더 생성
if not vault_path.exists():
    try:
        vault_path.mkdir(parents=True, exist_ok=True)
        st.sidebar.success(f"새로운 볼트 폴더가 생성되었습니다: {vault_path.name}")
    except Exception as e:
        st.sidebar.error(f"폴더 생성 실패: {e}")

# 2. 임베딩 및 LLM 초기화 (세션 상태 캐싱으로 속도 향상)
@st.cache_resource
def init_embeddings():
    # 한국어 임베딩 모델
    return HuggingFaceEmbeddings(
        model_name="jhgan/ko-sroberta-multitask",
        encode_kwargs={"normalize_embeddings": True}
    )

@st.cache_resource
def init_llm():
    # Gemini API 호출
    return ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

embeddings = init_embeddings()
llm = init_llm()

# 세션 상태 변수 초기화
if "last_question" not in st.session_state:
    st.session_state.last_question = ""
if "last_answer" not in st.session_state:
    st.session_state.last_answer = ""
if "last_sources" not in st.session_state:
    st.session_state.last_sources = []

# UI 시작
st.title("📋 옵시디언 연동형 초경량 RAG 시스템 (ObsiRAG)")
st.markdown("옵시디언 지식 베이스에 마크다운 문서를 자동 구조화하고, 지식 기반 Q&A 및 복습 관리를 수행합니다.")

tab1, tab2 = st.tabs(["📥 문서 업로드 & 개념 추출", "🔍 지식 검색 및 Q&A"])

# ----------------- TAB 1: 개념 추출 및 옵시디언 노트 저장 -----------------
with tab1:
    st.header("📄 외부 문서 지식 구조화")
    st.write("외부 문서(TXT, PDF)를 업로드하면 핵심 개념을 추출하여 옵시디언 마크다운 노트로 개별 저장합니다.")
    
    uploaded_file = st.file_uploader("문서 업로드 (PDF 또는 TXT)", type=["txt", "pdf"])
    
    if uploaded_file is not None:
        file_details = {"FileName": uploaded_file.name, "FileType": uploaded_file.type}
        st.write(file_details)
        
        # 파일 텍스트 추출
        text = ""
        if uploaded_file.type == "application/pdf":
            try:
                pdf_reader = PdfReader(uploaded_file)
                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            except Exception as e:
                st.error(f"PDF 파싱 실패: {e}")
        else:  # text/plain
            try:
                text = uploaded_file.read().decode("utf-8")
            except Exception as e:
                st.error(f"TXT 파싱 실패: {e}")
                
        st.text_area("추출된 원본 텍스트 미리보기", text[:500] + "...", height=150)
        
        if st.button("🚀 핵심 개념 추출 및 마크다운 파일 생성", key="extract_btn"):
            if not text.strip():
                st.warning("문서의 텍스트 내용이 비어있습니다.")
            else:
                with st.spinner("Gemini를 사용하여 개념을 분석 및 추출 중..."):
                    # 프롬프트 강제 사항 적용
                    prompt = f"""당신은 지식 구조화 전문가입니다. 아래 입력된 문서에서 핵심 개념들을 추출하여 옵시디언 마크다운 양식으로 작성하세요.

마크다운 출력 조건:
1. 중요도가 높은 개념은 개념명 옆에 [#중요] 태그를 붙이고 굵게 표시할 것. (예: **개념명** [#중요])
2. 일반 개념은 [#참고] 태그를 붙일 것.
3. 다른 개념과 연관성이 식별되면 [[연관개념명]] 형태로 내부 링크를 걸 것.

파일 저장 형식 조건:
각 개념을 개별 파일로 분리하기 위해, 각 개념은 반드시 아래 구조로 작성되어야 합니다:
### 개념: [개념명]
[여기에 개념 내용 마크다운...]

예시:
### 개념: 인덱싱
인덱싱 [#중요]은 문서를 [[벡터 데이터베이스]]에 저장하는 과정입니다.

입력 문서:
{text}
"""
                    try:
                        response = llm.invoke(prompt)
                        response_text = response.content
                        
                        # 개념 파싱 및 파일 저장
                        parts = re.split(r'### 개념:', response_text)
                        saved_files = []
                        
                        for part in parts:
                            part = part.strip()
                            if not part:
                                continue
                            lines = part.split("\n", 1)
                            concept_name = lines[0].replace("[", "").replace("]", "").strip()
                            content = lines[1].strip() if len(lines) > 1 else ""
                            
                            # 파일명으로 적합하지 않은 문자 제거
                            clean_filename = re.sub(r'[\\/*?:"<>|]', "", concept_name)
                            if not clean_filename:
                                continue
                                
                            file_path = vault_path / f"{clean_filename}.md"
                            
                            # 옵시디언 파일 저장 (open 활용)
                            with open(file_path, "w", encoding="utf-8") as f:
                                f.write(f"# {concept_name}\n\n{content}")
                                
                            saved_files.append(f"{clean_filename}.md")
                        
                        if saved_files:
                            st.success(f"🎉 성공적으로 {len(saved_files)}개의 개념 노트를 생성하여 저장했습니다!")
                            for sf in saved_files:
                                st.markdown(f"- 📄 `{sf}`")
                        else:
                            st.warning("추출된 개념 형식이 올바르지 않거나 파싱되지 않았습니다. 원본 출력을 확인해 주세요.")
                            st.text_area("Gemini 원본 출력", response_text)
                            
                    except Exception as e:
                        st.error(f"오류가 발생했습니다: {e}")

# ----------------- TAB 2: RAG 기반 Q&A 및 피드백 -----------------
with tab2:
    st.header("🔍 옵시디언 기반 지식 검색 및 Q&A")
    st.write("작성된 옵시디언 마크다운 메모들을 검색하여 근거에 기반한 답변을 드립니다.")
    
    # 옵시디언 문서 스캔
    md_files = list(vault_path.glob("*.md")) if vault_path.exists() else []
    # 복습 리스트 제외
    md_files = [f for f in md_files if f.name != "복습_필요_리스트.md"]
    
    st.write(f"현재 로드 가능한 옵시디언 문서 개수: `{len(md_files)}`개")
    
    question = st.text_input("질문을 입력하세요", placeholder="예: RAG의 두 가지 단계는 무엇인가요?")
    
    if st.button("질문하기"):
        if not question.strip():
            st.warning("질문을 입력해 주세요.")
        elif not md_files:
            st.error("옵시디언 폴더 내에 마크다운(*.md) 파일이 존재하지 않습니다. 먼저 1탭에서 문서를 업로드해 개념 노트를 만드세요.")
        else:
            with st.spinner("옵시디언 볼트를 스캔하여 답변을 검색 및 생성하는 중..."):
                try:
                    # 1. 문서 읽기 및 청킹
                    docs = []
                    for file_path in md_files:
                        with open(file_path, "r", encoding="utf-8") as f:
                            text_content = f.read()
                            docs.append(Document(page_content=text_content, metadata={"source": file_path.name}))
                    
                    text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
                    split_docs = text_splitter.split_documents(docs)
                    
                    # 2. FAISS 로컬 인덱싱
                    vectorstore = FAISS.from_documents(split_docs, embeddings)
                    retriever = vectorstore.as_retriever(search_kwargs={"k": 2})
                    
                    # 3. 검색 수행
                    retrieved_docs = retriever.invoke(question)
                    
                    # 4. 근거 기반 프롬프트 생성 및 LLM 호출
                    sources = list(set([doc.metadata.get("source", "알 수 없음") for doc in retrieved_docs]))
                    context = "\n\n".join([f"[{doc.metadata.get('source')}]:\n{doc.page_content}" for doc in retrieved_docs])
                    
                    prompt = f"""당신은 사용자의 옵시디언 지식 베이스를 바탕으로 답변하는 전문가입니다. 아래 제공된 참고 문서(Context)에 기반하여 질문(Question)에 대해 친절하게 한국어로 답변해 주세요.
반드시 제공된 내용만을 바탕으로 논리적으로 답변해야 하며, 정보가 없거나 부족하다면 억지로 꾸며내지 말고 솔직하게 모른다고 대답해 주세요.

Context:
{context}

Question: {question}

Answer:"""
                    
                    response = llm.invoke(prompt)
                    answer = response.content
                    
                    # 세션 상태에 마지막 질답 정보 저장 (피드백용)
                    st.session_state.last_question = question
                    st.session_state.last_answer = answer
                    st.session_state.last_sources = sources
                    
                except Exception as e:
                    st.error(f"RAG 프로세스 도중 에러가 발생했습니다: {e}")
                    
    # 결과가 있을 경우 화면에 출력
    if st.session_state.last_question:
        st.subheader("💡 Q&A 결과")
        
        # UI 표출 규칙: 출처 정보 상단 표출
        source_links = ", ".join([f"`{src}`" for src in st.session_state.last_sources])
        st.info(f"💡 본 답변의 근거가 된 옵시디언 노트: {source_links}")
        
        st.write(st.session_state.last_answer)
        
        st.write("---")
        # 📌 규칙 3: 미이해 개념 역저장 (피드백 루프)
        st.write("답변 내용이 이해하기 어려우셨나요? 복습 리스트에 등록하여 추후 공부하실 수 있습니다.")
        if st.button("⚠️ 이해하기 어려움 - 복습 노트에 추가", key="feedback_btn"):
            review_file = vault_path / "복습_필요_리스트.md"
            
            try:
                # 파일 끝에 덧붙여 쓰기 (open 활용)
                with open(review_file, "a", encoding="utf-8") as f:
                    f.write(f"\n\n## ❓ 질문: {st.session_state.last_question} #복습필요\n")
                    f.write(f"### 💡 AI의 기존 설명:\n{st.session_state.last_answer}\n")
                    f.write(f"*(근거 자료: {', '.join(st.session_state.last_sources)})*\n")
                    f.write("-" * 50 + "\n")
                    
                st.success("✅ 복습_필요_리스트.md 파일에 개념이 추가되었습니다! 옵시디언에서 `#복습필요` 태그를 검색해 복습해 보세요.")
            except Exception as e:
                st.error(f"복습 노트 기록 실패: {e}")
