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
if "last_papers" not in st.session_state:
    st.session_state.last_papers = []
if "last_saved_papers" not in st.session_state:
    st.session_state.last_saved_papers = []

# UI 시작
st.title("📋 옵시디언 연동형 초경량 RAG 시스템 (ObsiRAG)")
st.markdown("옵시디언 지식 베이스에 마크다운 문서를 자동 구조화하고, 지식 기반 Q&A 및 복습 관리를 수행합니다.")

tab1, tab2 = st.tabs(["📥 문서 업로드 & 개념 추출", "🔍 지식 검색 및 Q&A"])

# ----------------- TAB 1: 개념 추출 및 옵시디언 노트 저장 -----------------
with tab1:
    st.header("📄 외부 문서 지식 구조화")
    st.write("외부 문서(TXT, PDF)를 업로드하면 핵심 개념을 추출하여 옵시디언 마크다운 노트로 개별 저장합니다.")

    uploaded_files = st.file_uploader("문서 업로드 (PDF 또는 TXT)", type=["txt", "pdf"], accept_multiple_files=True)

    # 계층적 카테고리 분류 저장 옵션 추가
    hierarchy_option = st.checkbox(
        "📂 폴더 계층 구조(카테고리) 자동 분류 저장",
        value=True,
        help="체크하면 AI가 각 개념의 분야를 분석하여 폴더(카테고리) 단위로 계층 구조 폴더를 자동 생성하여 지식을 체계적으로 분류 저장합니다."
    )

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

                existing_concepts = [f.stem for f in vault_path.glob("**/*.md") if f.name != "복습_필요_리스트.md" and "venv" not in f.parts]
                existing_concepts_str = ", ".join(existing_concepts) if existing_concepts else "없음"

                with st.spinner(f"[{uploaded_file.name}] Gemini를 사용하여 개념을 분석 및 추출 중..."):
                    # 계층적 카테고리 지정 옵션에 따른 프롬프트 조건 분기
                    if hierarchy_option:
                        prompt_hierarchy_instructions = """
5. **계층 카테고리 지정 규칙 (중요)**: 각 개념의 분야(상위 분류)를 분석하여 `### 카테고리: [대분류/소분류]` 형식으로 지정해 주십시오. (예: 인공지능/머신러닝, 컴퓨터과학/알고리즘, 웹개발/백엔드)
   - 만약 분류하기 어렵거나 루트에 바로 저장할 경우 `### 카테고리: 없음`으로 표기하세요.

파일 저장 형식 조건:
각 개념을 개별 파일로 분리하기 위해, 각 개념은 반드시 아래 구조로 작성되어야 합니다:
### 개념: [개념명]
### 카테고리: [대분류/소분류]
[여기에 개념 내용 마크다운...]

예시:
### 개념: 인덱싱
### 카테고리: 데이터베이스/벡터DB
인덱싱 [#중요]은 문서를 [[벡터 데이터베이스]]에 저장하는 과정입니다.
"""
                    else:
                        prompt_hierarchy_instructions = """
파일 저장 형식 조건:
각 개념을 개별 파일로 분리하기 위해, 각 개념은 반드시 아래 구조로 작성되어야 합니다:
### 개념: [개념명]
[여기에 개념 내용 마크다운...]

예시:
### 개념: 인덱싱
인덱싱 [#중요]은 문서를 [[벡터 데이터베이스]]에 저장하는 과정입니다.
"""

                    prompt = f"""당신은 지식 구조화 전문가입니다. 아래 입력된 문서에서 핵심 개념들을 추출하여 옵시디언 마크다운 양식으로 작성하세요.

[현재 옵시디언 볼트에 이미 존재하는 기존 개념 노트 목록]:
({existing_concepts_str})

마크다운 출력 및 개념 명명 조건:
1. 중요도가 높은 개념은 개념명 옆에 [#중요] 태그를 붙이고 굵게 표시할 것. (예: **개념명** [#중요])
2. 일반 개념은 [#참고] 태그를 붙일 것.
3. 다른 개념과 연관성이 식별되면 [[연관개념명]] 형태로 내부 링크를 걸 것.
4. **개념명 통합 규칙 (중요)**: 새로 추출하는 개념이 위 기존 목록에 있는 개념명과 의미적으로 동일하거나 매우 유사한 개념(예: 한글/영어 번역어, 약어, 오타 등)인 경우, 절대 새로운 이름을 만들지 말고 반드시 **기존 목록의 개념명**을 동일하게 사용하십시오.
   - 예시: 기존 목록에 '딥러닝'이 존재하는데 새로운 추출 대상이 'Deep Learning'이나 'DL'인 경우, 새로운 파일을 생성하지 않도록 반드시 기존 개념명인 '딥러닝'을 그대로 사용하십시오.
{prompt_hierarchy_instructions}

입력 문서:
{text}
"""
                    try:
                        response = llm.invoke(prompt)
                        response_text = get_clean_string_content(response.content)

                        # 개념 파싱 및 파일 저장
                        parts = re.split(r'### 개념:', response_text)
                        saved_files = []

                        for part in parts:
                            part = part.strip()
                            if not part:
                                continue
                            lines = part.split("\n", 1)
                            concept_name = lines[0].replace("[", "").replace("]", "").strip()
                            rest = lines[1].strip() if len(lines) > 1 else ""

                            category = None
                            content = rest

                            # 카테고리 라인 파싱 및 본문 정제
                            if "### 카테고리:" in rest:
                                cat_split = rest.split("### 카테고리:", 1)
                                cat_lines = cat_split[1].split("\n", 1)
                                category_raw = cat_lines[0].replace("[", "").replace("]", "").strip()
                                if category_raw and category_raw.lower() not in ["없음", "none"]:
                                    # 폴더명 적합하지 않은 기호 제거 (하위 계층 경로인 / 문자는 보존)
                                    category = "/".join([re.sub(r'[\\*?:"<>|]', "", segment.strip()) for segment in category_raw.split("/")])
                                content = cat_lines[1].strip() if len(cat_lines) > 1 else ""

                                pre_content = cat_split[0].strip()
                                if pre_content:
                                    content = pre_content + "\n\n" + content

                            # 파일명으로 적합하지 않은 문자 제거
                            clean_filename = re.sub(r'[\\/*?:"<>|]', "", concept_name)
                            if not clean_filename:
                                continue

                            # 카테고리 폴더 경로 생성 (계층 구조 반영)
                            target_dir = vault_path
                            if category:
                                target_dir = vault_path / category
                                target_dir.mkdir(parents=True, exist_ok=True)

                            file_path = target_dir / f"{clean_filename}.md"

                            # 옵시디언 파일 저장 (개념 파일 병합 로직 - Merge 적용)
                            if file_path.exists():
                                with open(file_path, "a", encoding="utf-8") as f:
                                    f.write(f"\n\n{content}")
                            else:
                                with open(file_path, "w", encoding="utf-8") as f:
                                    f.write(f"# {concept_name}\n\n{content}")

                            if category:
                                saved_files.append(f"{category}/{clean_filename}.md")
                            else:
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

    # 옵시디언 문서 스캔 (서브폴더 계층 구조까지 전체 검색)
    md_files = list(vault_path.glob("**/*.md")) if vault_path.exists() else []
    # 복습 리스트 및 파이썬 캐시/가상환경 경로 제거
    md_files = [f for f in md_files if f.name != "복습_필요_리스트.md" and "venv" not in f.parts]

    st.write(f"현재 로드 가능한 옵시디언 문서 개수: `{len(md_files)}`개 (계층 구조 포함)")

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
                        st.session_state.last_saved_papers = data.get("saved_papers", [])

                        # 관련 학술 논문 결과 리셋 (사용자가 수동으로 버튼을 눌렀을 때만 검색하도록 변경)
                        st.session_state.last_papers = []
                    elif response.status_code == 404:
                        st.error("백엔드: 옵시디언 폴더 내에 문서가 존재하지 않습니다.")
                    else:
                        st.error(f"서버 에러가 발생했습니다: {response.text}")
                except Exception as e:
                    st.error(f"백엔드 서버 연결 실패: {e}\n(FastAPI 서버가 구동 중인지 확인해 주세요. 실행 명령어: uvicorn backend.main:app)")

    # 결과가 있을 경우 화면에 출력
    if st.session_state.last_question:
        st.subheader("💡 Q&A 결과")

        # UI 표출 규칙: 출처 정보 상단 표출 (클릭 시 옵시디언 앱에서 바로 열기 지원)
        import urllib.parse
        source_links_list = []
        for src in st.session_state.last_sources:
            obsidian_uri = f"obsidian://open?vault={urllib.parse.quote(vault_path.name)}&file={urllib.parse.quote(src)}"
            source_links_list.append(f"[{src}]({obsidian_uri})")
        source_links = ", ".join(source_links_list)
        st.info(f"💡 본 답변의 근거가 된 옵시디언 노트 (클릭 시 앱에서 바로가기): {source_links}")

        st.write(st.session_state.last_answer)

        # 기저장된 논문 정보 표출
        if st.session_state.last_saved_papers:
            st.write("")
            st.subheader("📌 이 개념 노트에 이미 저장되어 있는 학술 논문")
            for idx, p in enumerate(st.session_state.last_saved_papers, 1):
                with st.expander(f"📖 [{idx}] {p['title']} (출처: {p['source_file']})"):
                    st.markdown(f"**👤 저자**: {p['authors']}")
                    st.markdown(f"**🔗 링크**: [ArXiv 논문 페이지]({p['link']})")
                    st.markdown(f"**💡 AI 요약 (한글)**: {p['summary']}")

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

            else:  # 새로운 노트로 개별 저장 (카테고리 폴더 경로 설정 가능)
                # 1. 기존 카테고리 스캔
                all_vault_cats = []
                for f in vault_path.glob("**/*.md"):
                    if f.name == "복습_필요_리스트.md" or "venv" in f.parts:
                        continue
                    rel_parent = f.parent.relative_to(vault_path)
                    if str(rel_parent) != ".":
                        cat_str = str(rel_parent).replace("\\", "/")
                        if cat_str not in all_vault_cats:
                            all_vault_cats.append(cat_str)
                all_vault_cats.sort()

                # 2. 추천 카테고리 추출 (Q&A 유사문서 기준 최대 3개)
                recommended_cats = []
                for doc in st.session_state.suggested_merge_targets:
                    parts = doc.split("/")
                    if len(parts) > 1:
                        cat = "/".join(parts[:-1])
                        if cat not in recommended_cats:
                            recommended_cats.append(cat)
                recommended_cats = recommended_cats[:3]

                # 3. 드롭다운 목록 구성
                cat_dropdown_options = ["직접 입력", "루트 (폴더 없음)"]
                for rc in recommended_cats:
                    cat_dropdown_options.append(f"⭐️ 추천: {rc}")
                for ac in all_vault_cats:
                    if ac not in recommended_cats:
                        cat_dropdown_options.append(ac)

                col_name_qa, col_select_cat = st.columns([1, 1])
                with col_name_qa:
                    custom_concept_name = st.text_input(
                        "저장할 개념 노트 이름 (제목)",
                        value=st.session_state.suggested_title,
                        key="concept_name_input"
                    )
                with col_select_cat:
                    selected_cat_option = st.selectbox(
                        "카테고리 선택",
                        cat_dropdown_options,
                        key="concept_category_selectbox"
                    )

                # "직접 입력" 선택 시 텍스트 입력창 출력
                custom_qa_category = ""
                if selected_cat_option == "직접 입력":
                    custom_qa_category = st.text_input(
                        "새 카테고리 입력 (예: 인공지능/딥러닝)",
                        value="",
                        key="concept_category_input"
                    )
                elif selected_cat_option == "루트 (폴더 없음)":
                    custom_qa_category = ""
                else:
                    custom_qa_category = selected_cat_option.replace("⭐️ 추천: ", "")

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
                                    "category": custom_qa_category.strip() if custom_qa_category.strip() else None,
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

    # 📌 관련 학술 논문 추천 (상위 4개) UI 추가 - Q&A 블록 외부로 분리(독립 노출)
    st.write("---")
    st.subheader("📚 학술 논문 검색 및 추천 (상위 4개)")

    col_paper_query, col_paper_btn = st.columns([3, 1])
    with col_paper_query:
        paper_custom_query = st.text_input(
            "검색하고 싶은 논문 주제/키워드 입력",
            value=st.session_state.last_question if st.session_state.last_question else "",
            placeholder="예: deep learning, RAG, transformer...",
            key="paper_custom_query_input"
        )
    with col_paper_btn:
        st.write("") # 상단 마진 패딩
        trigger_search = st.button("🔍 논문 검색", key="search_papers_trigger_btn_custom")

    if trigger_search:
        if not paper_custom_query.strip():
            st.error("논문 검색 키워드를 입력해 주세요.")
        else:
            with st.spinner("학술 논문 데이터베이스 검색 및 AI 추천 분석 중..."):
                try:
                    import requests
                    paper_response = requests.post(
                        "http://127.0.0.1:8000/api/v1/papers/search",
                        json={"query": paper_custom_query.strip()}
                    )
                    if paper_response.status_code == 200:
                        st.session_state.last_papers = paper_response.json()
                        if not st.session_state.last_papers:
                            st.warning("이 키워드에 관련해 추천할 학술 논문을 찾을 수 없거나 일시적 통신 오류가 발생했습니다.")
                        else:
                            st.rerun()
                    else:
                        st.error(f"논문 추천 실패: {paper_response.text}")
                except Exception as e:
                    st.error(f"백엔드 연결 실패: {e}")

    if st.session_state.last_papers:
        st.write("검색하신 키워드와 관련된 아카이브(ArXiv)의 최신 학술 논문 및 AI 한글 요약입니다.")

        # 논문 저장을 위해 병합할 지식 노트 목록 스캔
        existing_notes_for_paper = [
            f.relative_to(vault_path) for f in vault_path.glob("**/*.md")
            if f.name != "복습_필요_리스트.md" and "venv" not in f.parts
        ]

        for idx, paper in enumerate(st.session_state.last_papers, 1):
            with st.expander(f"📖 [{idx}] {paper['title']}"):
                st.markdown(f"**👤 저자**: {paper['authors']}")
                st.markdown(f"**🔗 링크**: [ArXiv 논문 페이지]({paper['link']})")
                st.markdown(f"**💡 AI 요약 (한글)**: {paper['summary']}")

                st.write("")

                # 이 논문과 유사한 기존 노트 상위 5개 미리 검색 (병합 및 카테고리 추천용)
                try:
                    import requests
                    sim_response = requests.post(
                        "http://127.0.0.1:8000/api/v1/obsidian/similar_docs",
                        json={
                            "query": paper["title"],
                            "vault_path": str(vault_path)
                        }
                    )
                    if sim_response.status_code == 200:
                        related_notes = sim_response.json()
                    else:
                        related_notes = []
                except Exception:
                    related_notes = []

                # 유사 문서 검색 실패 시 폴백
                if not related_notes:
                    related_notes = [str(f) for f in existing_notes_for_paper[:5]]

                # 1. 저장 방식 라디오 버튼 분리
                paper_save_mode = st.radio(
                    "저장 방식 선택",
                    ["기존 노트에 병합하기", "새로운 노트로 개별 저장"],
                    key=f"paper_save_mode_{idx}",
                    horizontal=True
                )

                if paper_save_mode == "기존 노트에 병합하기":
                    if not related_notes:
                        st.info("병합할 기존 지식 노트가 존재하지 않습니다. '새로운 노트로 개별 저장'을 선택해 주십시오.")
                    else:
                        col_select, col_btn = st.columns([2, 1])
                        with col_select:
                            selected_doc = st.selectbox(
                                "병합할 연관 지식 노트 선택 (유사도 순 최대 5개)",
                                related_notes,
                                key=f"paper_target_doc_{idx}"
                            )
                        with col_btn:
                            st.write("") # 상단 라벨 간격 패딩
                            if st.button("💾 논문 출처 추가", key=f"save_paper_btn_{idx}"):
                                try:
                                    concept_rel_path = selected_doc.replace(".md", "")
                                    paper_content = (
                                        f"\n\n### 📚 관련 학술 논문 출처: {paper['title']}\n"
                                        f"- **저자**: {paper['authors']}\n"
                                        f"- **링크**: {paper['link']}\n"
                                        f"- **AI 번역 요약**: {paper['summary']}\n"
                                    )
                                    save_response = requests.post(
                                        "http://127.0.0.1:8000/api/v1/obsidian/save_concept",
                                        json={
                                            "concept_name": concept_rel_path,
                                            "content": paper_content,
                                            "category": None,
                                            "vault_path": str(vault_path)
                                        }
                                    )
                                    if save_response.status_code == 201:
                                        st.success("✅ 논문 출처가 기존 노트에 성공적으로 병합되었습니다!")
                                    else:
                                        st.error(f"출처 추가 실패: {save_response.text}")
                                except Exception as e:
                                    st.error(f"백엔드 연결 실패: {e}")

                else:  # 새로운 노트로 개별 저장 (카테고리 지정 가능)
                    # AI가 추천하는 깔끔한 파일 제목 추출 (특수 문자 제거)
                    clean_paper_title = re.sub(r'[\\/*?:"<>|]', "", paper["title"])
                    if len(clean_paper_title) > 30:
                        clean_paper_title = clean_paper_title[:27] + "..."

                    # 1) 전체 카테고리 스캔
                    all_vault_cats = []
                    for f in vault_path.glob("**/*.md"):
                        if f.name == "복습_필요_리스트.md" or "venv" in f.parts:
                            continue
                        rel_parent = f.parent.relative_to(vault_path)
                        if str(rel_parent) != ".":
                            cat_str = str(rel_parent).replace("\\", "/")
                            if cat_str not in all_vault_cats:
                                all_vault_cats.append(cat_str)
                    all_vault_cats.sort()

                    # 2) 추천 카테고리 추출 (이 논문과 유사도가 높은 지식노트 부모폴더 기준 3개)
                    paper_recommended_cats = []
                    for doc in related_notes:
                        parts = doc.split("/")
                        if len(parts) > 1:
                            cat = "/".join(parts[:-1])
                            if cat not in paper_recommended_cats:
                                paper_recommended_cats.append(cat)
                    paper_recommended_cats = paper_recommended_cats[:3]

                    # 3) 드롭다운 목록 빌드 (학술논문 기본값 처리)
                    paper_cat_options = ["직접 입력", "루트 (폴더 없음)", "학술논문"]
                    for prc in paper_recommended_cats:
                        if prc != "학술논문" and prc not in paper_cat_options:
                            paper_cat_options.append(f"⭐️ 추천: {prc}")
                    for ac in all_vault_cats:
                        if ac != "학술논문" and ac not in paper_recommended_cats and ac not in paper_cat_options:
                            paper_cat_options.append(ac)

                    col_title, col_cat_sel = st.columns([1.5, 1.5])
                    with col_title:
                        custom_paper_note_title = st.text_input(
                            "저장할 새 개념 노트 이름 (제목)",
                            value=clean_paper_title,
                            key=f"new_paper_title_{idx}"
                        )
                    with col_cat_sel:
                        selected_paper_cat = st.selectbox(
                            "카테고리 선택",
                            paper_cat_options,
                            index=2, # 기본값: "학술논문"
                            key=f"new_paper_cat_select_{idx}"
                        )

                    # 직접 입력 대응 및 값 추출
                    custom_paper_cat_val = ""
                    if selected_paper_cat == "직접 입력":
                        custom_paper_cat_val = st.text_input(
                            "새 카테고리 입력 (예: 인공지능/논문)",
                            value="",
                            key=f"new_paper_cat_input_{idx}"
                        )
                    elif selected_paper_cat == "루트 (폴더 없음)":
                        custom_paper_cat_val = ""
                    else:
                        custom_paper_cat_val = selected_paper_cat.replace("⭐️ 추천: ", "")

                    # 저장 버튼 단독 배치로 꼬임 방지
                    if st.button("💾 새 노트로 저장", key=f"save_new_paper_btn_{idx}"):
                        if not custom_paper_note_title.strip():
                            st.error("노트 이름을 입력해 주세요.")
                        else:
                            try:
                                paper_file_content = (
                                    f"- **논문명**: {paper['title']}\n"
                                    f"- **저자**: {paper['authors']}\n"
                                    f"- **링크**: {paper['link']}\n\n"
                                    f"### 💡 AI 번역 요약\n{paper['summary']}"
                                )
                                save_response = requests.post(
                                    "http://127.0.0.1:8000/api/v1/obsidian/save_concept",
                                    json={
                                        "concept_name": custom_paper_note_title.strip(),
                                        "content": paper_file_content,
                                        "category": custom_paper_cat_val.strip() if custom_paper_cat_val.strip() else None,
                                        "vault_path": str(vault_path)
                                    }
                                )
                                if save_response.status_code == 201:
                                    st.success("✅ 새로운 지식 노트로 저장되었습니다!")
                                else:
                                    st.error(f"저장 실패: {save_response.text}")
                            except Exception as e:
                                st.error(f"백엔드 연결 실패: {e}")

        # 논문 결과 닫기 버튼 추가
        st.write("")
        if st.button("🔄 논문 결과 닫기 및 초기화", key="reset_papers_btn"):
            st.session_state.last_papers = []
            st.rerun()
