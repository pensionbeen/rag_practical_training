import os
import glob
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_google_genai import ChatGoogleGenerativeAI

# .env 파일 로드 및 API 키 확인
load_dotenv()

if not os.getenv("GOOGLE_API_KEY"):
    print("=" * 60)
    print("🔑 Google Gemini API Key가 필요합니다.")
    print("API Key는 https://aistudio.google.com/ 에서 무료로 발급받으실 수 있습니다.")
    print("=" * 60)
    api_key_input = input("Google API Key를 입력하세요: ").strip()
    if api_key_input:
        with open(".env", "w", encoding="utf-8") as f:
            f.write(f"GOOGLE_API_KEY={api_key_input}\n")
        os.environ["GOOGLE_API_KEY"] = api_key_input
        print("✅ .env 파일에 API Key가 저장되었습니다.")
    else:
        print("❌ API Key가 입력되지 않아 종료합니다.")
        exit(1)

# 문서 폴더 경로 (이 스크립트 기준 상대 경로)
DOCS_DIR = Path(__file__).parent / "sample_docs"
INDEX_DIR = Path(__file__).parent / "faiss_index"

# 1. 문서 파일 로드 함수
def load_txt_documents(directory):
    documents = []
    if not os.path.exists(directory):
        os.makedirs(directory)
        print(f"'{directory}' 폴더가 없어 새로 생성했습니다. 텍스트 파일을 추가해 주세요.")
        return documents
        
    txt_files = glob.glob(os.path.join(directory, "*.txt"))
    for file_path in txt_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
                # 파일 이름을 메타데이터 소스로 추가하여 어떤 문서에서 왔는지 추적 가능하게 함
                doc = Document(page_content=text, metadata={"source": os.path.basename(file_path)})
                documents.append(doc)
        except Exception as e:
            print(f"파일 로드 오류 ({file_path}): {e}")
    return documents

# 2. 임베딩 모델 설정 (jhgan/ko-sroberta-multitask)
print("Loading Korean Embedding Model ('jhgan/ko-sroberta-multitask')...")
embeddings = HuggingFaceEmbeddings(
    model_name="jhgan/ko-sroberta-multitask",
    encode_kwargs={"normalize_embeddings": True}
)

# 3. 벡터 데이터베이스 로드 및 인덱싱 처리
vectorstore = None

# 이미 만들어진 로컬 인덱스가 있다면 그것을 사용하고, 없다면 텍스트 문서를 읽어 새로 만듭니다.
if os.path.exists(INDEX_DIR):
    print("✅ 기존에 저장된 FAISS 인덱스를 로드합니다...")
    vectorstore = FAISS.load_local(INDEX_DIR, embeddings, allow_dangerous_deserialization=True)
else:
    print("📝 새로운 문서 데이터를 분석 및 인덱싱합니다...")
    raw_docs = load_txt_documents(DOCS_DIR)
    
    if not raw_docs:
        print("❌ 'docs' 폴더 내에 읽을 수 있는 텍스트(*.txt) 파일이 없습니다.")
        print("기본 테스트용 문서를 가상으로 생성합니다.")
        raw_docs = [
            Document(page_content="가상 문서: 아직 등록된 사내 규정 문서가 없습니다. docs 폴더에 텍스트 파일을 올려주세요.", metadata={"source": "none"})
        ]
        
    # 텍스트 분할
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
    split_docs = text_splitter.split_documents(raw_docs)
    
    # 벡터 DB 구축 및 로컬 저장
    vectorstore = FAISS.from_documents(split_docs, embeddings)
    vectorstore.save_local(INDEX_DIR)
    print(f"💾 FAISS 인덱스가 '{INDEX_DIR}' 폴더에 로컬 저장되었습니다.")

# 4. 검색기(Retriever) 설정 (k=2)
retriever = vectorstore.as_retriever(search_kwargs={"k": 2})

# 5. 생성 LLM 모델 로드 (Gemini-2.5-Flash)
print("Connecting to Google Gemini API (gemini-2.5-flash)...")
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

def ask(question: str):
    # 관련 문서 검색
    retrieved_docs = retriever.invoke(question)
    
    # 검색된 문서를 컨텍스트 문자열로 결합
    context_list = []
    for idx, doc in enumerate(retrieved_docs, 1):
        source = doc.metadata.get("source", "알 수 없음")
        context_list.append(f"[출처: {source}]\n{doc.page_content.strip()}")
    context = "\n\n".join(context_list)
    
    # Prompt 작성
    prompt = f"""당신은 유용한 AI 어시스턴트입니다. 아래 제공된 참고 문서(Context)에 기반하여 질문(Question)에 대해 친절하게 한국어로 답변해 주세요.
답변할 때 참고 문서의 내용을 바탕으로 대답해야 하며, 지어내지 말아 주세요.

Context:
{context}

Question: {question}

Answer:"""
    
    # 답변 생성
    response = llm.invoke(prompt)
    answer = response.content
    
    # 결과 출력
    print("=" * 60)
    print(f"질문 (Question): {question}")
    print("=" * 60)
    print("검색된 근거 조각 (Retrieved Chunks):")
    for idx, doc in enumerate(retrieved_docs, 1):
        source = doc.metadata.get("source", "알 수 없음")
        print(f"\n[Chunk {idx}] - 출처: {source}")
        print(doc.page_content.strip())
    print("-" * 60)
    print(f"생성 답변 (Generated Answer):\n{answer}")
    print("=" * 60)
    
    return answer

if __name__ == "__main__":
    print("=" * 60)
    print("📁 로컬 문서 기반 RAG 질의응답 시스템이 준비되었습니다!")
    print(" 'docs/' 폴더 내의 텍스트 파일 내용을 기반으로 답변합니다.")
    print(" 종료하려면 'exit' 또는 'quit'을 입력하세요.")
    print("=" * 60)
    
    while True:
        try:
            user_question = input("\n질문을 입력하세요 > ").strip()
            if not user_question:
                continue
            if user_question.lower() in ["exit", "quit"]:
                print("시스템을 종료합니다. 감사합니다!")
                break
            
            ask(user_question)
        except (KeyboardInterrupt, EOFError):
            print("\n시스템을 종료합니다. 감사합니다!")
            break
