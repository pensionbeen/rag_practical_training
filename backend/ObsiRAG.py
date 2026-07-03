import os
import re
from pathlib import Path
from dotenv import load_dotenv
import streamlit as st
from pypdf import PdfReader

from langchain_openai import ChatOpenAI

# 0. API 키 관리 및 환경변수 로드
load_dotenv()

st.set_page_config(page_title="ObsiRAG: 옵시디언 연동형 RAG", page_icon="📋", layout="wide")

# API Key 검증
if not os.getenv("OPENAI_API_KEY"):
    st.title("📋 ObsiRAG 시스템 설정")
    st.warning("🔑 OpenAI API Key가 설정되지 않았습니다.")
    st.markdown("API Key는 [OpenAI Platform](https://platform.openai.com/api-keys)에서 발급받으실 수 있습니다.")
    api_key_input = st.text_input("OpenAI API Key를 입력하세요", type="password")
    if st.button("API Key 저장"):
        if api_key_input:
            with open(".env", "w", encoding="utf-8") as f:
                f.write(f"OPENAI_API_KEY={api_key_input}\n")
            st.success("✅ .env 파일에 API Key가 저장되었습니다! 새로고침하여 시작해 주세요.")
            st.rerun()
        else:
            st.error("API Key를 입력해 주세요.")
    st.stop()

# 1. 경로 관리 및 초기화 (pathlib.Path 사용)
st.sidebar.title("📁 옵시디언 경로 설정")

# .env에서 불러온 이전 커스텀 경로가 있으면 복원하고, 없으면 기본 디렉토리 설정
env_vault_path = os.getenv("OBSIDIAN_VAULT_PATH")
if env_vault_path:
    default_vault_path = env_vault_path
else:
    default_vault_path = str(Path.cwd() / "my_obsidian_vault")

vault_path_str = st.sidebar.text_input("옵시디언 볼트(Vault) 절대 경로", default_vault_path)
vault_path = Path(vault_path_str)

# 경로가 새로 변경되었다면 .env에 즉시 저장하여 영구 기억
if env_vault_path != vault_path_str:
    try:
        env_lines = []
        if Path(".env").exists():
            with open(".env", "r", encoding="utf-8") as f:
                env_lines = f.readlines()
        
        env_lines = [line for line in env_lines if not line.startswith("OBSIDIAN_VAULT_PATH=")]
        env_lines.append(f"OBSIDIAN_VAULT_PATH={vault_path_str}\n")
        
        with open(".env", "w", encoding="utf-8") as f:
            f.writelines(env_lines)
            
        os.environ["OBSIDIAN_VAULT_PATH"] = vault_path_str
        st.sidebar.success("💾 변경된 경로가 영구 저장되었습니다.")
    except Exception as e:
        pass

# 폴더 생성
if not vault_path.exists():
    try:
        vault_path.mkdir(parents=True, exist_ok=True)
        st.sidebar.success(f"새로운 볼트 폴더가 생성되었습니다: {vault_path.name}")
    except Exception as e:
        st.sidebar.error(f"폴더 생성 실패: {e}")

# 2. LLM 초기화 (세션 상태 캐싱으로 속도 향상)
@st.cache_resource
def init_llm():
    # OpenAI API 호출
    return ChatOpenAI(model="gpt-4o-mini", temperature=0)

llm = init_llm()

# 세션 상태 변수 초기화
if "last_question" not in st.session_state:
    st.session_state.last_question = ""
if "last_answer" not in st.session_state:
    st.session_state.last_answer = ""
if "last_sources" not in st.session_state:
    st.session_state.last_sources = []
if "fallback_used" not in st.session_state:
    st.session_state.fallback_used = False
if "suggested_title" not in st.session_state:
    st.session_state.suggested_title = ""
if "suggested_merge_targets" not in st.session_state:
    st.session_state.suggested_merge_targets = []

# UI 시작
st.title("📋 옵시디언 연동형 초경량 RAG 시스템 (ObsiRAG)")
st.markdown("옵시디언 지식 베이스에 마크다운 문서를 자동 구조화하고, 지식 기반 Q&A 및 복습 관리를 수행합니다.")

tab1, tab2 = st.tabs(["📥 문서 업로드 & 개념 추출", "🔍 지식 검색 및 Q&A"])

# ----------------- TAB 1: 개념 추출 및 옵시디언 노트 저장 -----------------
with tab1:
    st.header("📄 외부 문서 지식 구조화")
    st.write("외부 문서(TXT, PDF)를 업로드하면 핵심 개념을 추출하여 옵시디언 마크다운 노트로 개별 저장합니다.")

    uploaded_files = st.file_uploader("문서 업로드 (PDF 또는 TXT)", type=["txt", "pdf"], accept_multiple_files=True)
    
    if uploaded_files:
        st.write(f"업로드된 파일 개수: `{len(uploaded_files)}`개")
        
        if st.button("🚀 핵심 개념 추출 및 마크다운 파일 생성", key="extract_btn"):
            for idx, uploaded_file in enumerate(uploaded_files, 1):
                st.write("---")
                st.markdown(f"### 📂 [{idx}/{len(uploaded_files)}] `{uploaded_file.name}` 처리 중...")
                
                # 파일 텍스트 추출
                text = ""
                if uploaded_file.type == "application/pdf":
                    try:
                        from pdf_parser import parse_pdf_to_chunks
                        chunks = parse_pdf_to_chunks(uploaded_file)
                        text = "\n\n".join(chunks)
                    except Exception as e:
                        st.error(f"[{uploaded_file.name}] PDF 파싱 실패: {e}")
                        continue
                else:  # text/plain
                    try:
                        uploaded_file.seek(0)
                        text = uploaded_file.read().decode("utf-8")
                    except Exception as e:
                        st.error(f"[{uploaded_file.name}] TXT 파싱 실패: {e}")
                        continue
                        
                if not text.strip():
                    st.warning(f"[{uploaded_file.name}] 문서의 텍스트 내용이 비어있습니다.")
                    continue
                    
                st.text_area(f"[{uploaded_file.name}] 추출된 텍스트 미리보기", text[:300] + "...", height=100, key=f"preview_{idx}")
                
                existing_concepts = [f.stem for f in vault_path.glob("*.md") if f.name != "복습_필요_리스트.md"]
                existing_concepts_str = ", ".join(existing_concepts) if existing_concepts else "없음"
                
                with st.spinner(f"[{uploaded_file.name}] Gemini를 사용하여 개념을 분석 및 추출 중..."):
                    # 프롬프트 강제 사항 및 개념명 통일 규칙 적용
                    prompt = f"""당신은 지식 구조화 전문가입니다. 아래 입력된 문서에서 핵심 개념들을 추출하여 옵시디언 마크다운 양식으로 작성하세요.

[현재 옵시디언 볼트에 이미 존재하는 기존 개념 노트 목록]:
({existing_concepts_str})

마크다운 출력 및 개념 명명 조건:
1. 중요도가 높은 개념은 개념명 옆에 [#중요] 태그를 붙이고 굵게 표시할 것. (예: **개념명** [#중요])
2. 일반 개념은 [#참고] 태그를 붙일 것.
3. 다른 개념과 연관성이 식별되면 [[연관개념명]] 형태로 내부 링크를 걸 것.
4. **개념명 통합 규칙 (중요)**: 새로 추출하는 개념이 위 기존 목록에 있는 개념명과 의미적으로 동일하거나 매우 유사한 개념(예: 한글/영어 번역어, 약어, 오타 등)인 경우, 절대 새로운 이름을 만들지 말고 반드시 **기존 목록의 개념명**을 동일하게 사용하십시오.
   - 예시: 기존 목록에 '딥러닝'이 존재하는데 새로운 추출 대상이 'Deep Learning'이나 'DL'인 경우, 새로운 파일을 생성하지 않도록 반드시 기존 개념명인 '딥러닝'을 그대로 사용하십시오.

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

                            # 옵시디언 파일 저장 (개념 파일 병합 로직 - Merge 적용)
                            if file_path.exists():
                                with open(file_path, "a", encoding="utf-8") as f:
                                    f.write(f"\n\n{content}")
                            else:
                                with open(file_path, "w", encoding="utf-8") as f:
                                    f.write(f"# {concept_name}\n\n{content}")

                            saved_files.append(f"{clean_filename}.md")

                        if saved_files:
                            st.success(f"🎉 [{uploaded_file.name}] {len(saved_files)}개의 개념 노트를 성공적으로 저장했습니다!")
                            for sf in saved_files:
                                st.markdown(f"- 📄 `{sf}`")
                        else:
                            st.warning(f"[{uploaded_file.name}] 추출된 개념 형식이 올바르지 않거나 파싱되지 않았습니다.")
                            st.text_area("Gemini 원본 출력", response_text, key=f"raw_out_{idx}")

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
            with st.spinner("백엔드 서버를 통해 답변을 검색 및 생성하는 중..."):
                try:
                    import requests
                    response = requests.post(
                        "http://127.0.0.1:8000/api/v1/ask",
                        json={
                            "query": question,
                            "vault_path": str(vault_path)
                        }
                    )
                    if response.status_code == 200:
                        data = response.json()
                        st.session_state.last_question = question
                        st.session_state.last_answer = data.get("response", "")
                        st.session_state.last_sources = [data.get("source_file", "")]
                        st.session_state.fallback_used = data.get("fallback_used", False)
                        st.session_state.suggested_title = data.get("suggested_title", "")
                        st.session_state.suggested_merge_targets = data.get("suggested_merge_targets", [])
                    elif response.status_code == 404:
                        st.error("백엔드: 옵시디언 폴더 내에 문서가 존재하지 않습니다.")
                    else:
                        st.error(f"서버 에러가 발생했습니다: {response.text}")
                except Exception as e:
                    st.error(f"백엔드 서버 연결 실패: {e}\n(FastAPI 서버가 구동 중인지 확인해 주세요. 실행 명령어: uvicorn backend.main:app)")

    # 결과가 있을 경우 화면에 출력
    if st.session_state.last_question:
        st.subheader("💡 Q&A 결과")
        
        # UI 표출 규칙: 출처 정보 상단 표출
        source_links = ", ".join([f"`{src}`" for src in st.session_state.last_sources])
        st.info(f"💡 본 답변의 근거가 된 옵시디언 노트: {source_links}")
        
        st.write(st.session_state.last_answer)

        # 만약 외부 LLM 지식(Fallback)을 활용해 새로운 지식이 생성된 경우
        if st.session_state.fallback_used:
            st.warning("💡 이 질문은 옵시디언 지식 베이스에 없는 내용입니다. 아래 설정을 통해 옵시디언 노트로 저장하실 수 있습니다.")
            
            # 저장 방식 선택
            save_mode = st.radio(
                "저장 방식 선택", 
                ["기존 노트에 병합하기", "새로운 노트로 개별 저장"], 
                horizontal=True,
                key="save_mode_radio"
            )
            
            if save_mode == "기존 노트에 병합하기":
                # 백엔드에서 검색된 유사도가 높은 상위 3개 문서 목록
                merge_targets = st.session_state.suggested_merge_targets
                
                if not merge_targets:
                    st.info("병합을 추천할 만한 기존 지식 노트가 존재하지 않습니다. '새로운 노트로 개별 저장'을 선택해 주십시오.")
                else:
                    selected_existing_note = st.selectbox(
                        "병합 추천 기존 지식 노트 (유사도 순 최대 3개)",
                        merge_targets,
                        key="merge_note_select"
                    )
                    
                    if st.button("💾 선택한 기존 노트에 병합", key="merge_existing_btn"):
                        try:
                            # 확장자(.md)를 뺀 상대 경로 전달
                            concept_rel_path = selected_existing_note.replace(".md", "")
                            
                            import requests
                            save_response = requests.post(
                                "http://127.0.0.1:8000/api/v1/obsidian/save_concept",
                                json={
                                    "concept_name": concept_rel_path,
                                    "content": f"\n\n## ❓ 추가 질문: {st.session_state.last_question} [#참고]\n{st.session_state.last_answer}",
                                    "category": None,
                                    "vault_path": str(vault_path)
                                }
                            )
                            if save_response.status_code == 201:
                                st.success(f"✅ 성공적으로 '{selected_existing_note}'에 병합되었습니다!")
                                st.session_state.fallback_used = False # 상태 초기화
                            else:
                                st.error(f"병합 실패: {save_response.text}")
                        except Exception as e:
                            st.error(f"백엔드 연결 실패: {e}")
                            
            else:  # 새로운 노트로 개별 저장 (불필요한 카테고리 폴더 제거)
                custom_concept_name = st.text_input(
                    "저장할 개념 노트 이름 (제목)", 
                    value=st.session_state.suggested_title,
                    key="concept_name_input"
                )
                
                if st.button("💾 옵시디언에 새 개념 노드로 저장", key="save_concept_btn"):
                    if not custom_concept_name.strip():
                        st.error("개념 노트 이름을 입력해 주세요.")
                    else:
                        try:
                            import requests
                            save_response = requests.post(
                                "http://127.0.0.1:8000/api/v1/obsidian/save_concept",
                                json={
                                    "concept_name": custom_concept_name.strip(),
                                    "content": f"## ❓ 질문: {st.session_state.last_question} [#참고]\n{st.session_state.last_answer}",
                                    "category": None, # 카테고리 제거로 루트에 바로 단독 저장
                                    "vault_path": str(vault_path)
                                }
                            )
                            if save_response.status_code == 201:
                                st.success(f"✅ 성공적으로 '{custom_concept_name}.md' 지식 노트가 저장되었습니다!")
                                st.session_state.fallback_used = False # 상태 초기화
                            else:
                                st.error(f"지식 저장 실패: {save_response.text}")
                        except Exception as e:
                            st.error(f"백엔드 연결 실패: {e}")

        st.write("---")
        # 📌 규칙 3: 미이해 개념 역저장 (피드백 루프)
        st.write("답변 내용이 이해하기 어려우셨나요? 복습 리스트에 등록하여 추후 공부하실 수 있습니다.")
        if st.button("⚠️ 이해하기 어려움 - 복습 노트에 추가", key="feedback_btn"):
            try:
                import requests
                # 가장 유사도가 높았던 RAG 근거 파일명을 백엔드로 전달
                primary_source = st.session_state.last_sources[0] if st.session_state.last_sources else None
                
                response = requests.post(
                    "http://127.0.0.1:8000/api/v1/obsidian/save",
                    json={
                        "question": st.session_state.last_question,
                        "answer": st.session_state.last_answer,
                        "source_file": primary_source,
                        "vault_path": str(vault_path)
                    }
                )
                if response.status_code == 201:
                    data = response.json()
                    st.success(f"✅ 완료: {data.get('detail', '복습 파일에 추가되었습니다!')}")
                else:
                    st.error(f"복습 저장 실패: {response.text}")
            except Exception as e:
                st.error(f"백엔드 서버 연결 실패: {e}\n(FastAPI 서버가 구동 중인지 확인해 주세요. 실행 명령어: uvicorn backend.main:app)")
