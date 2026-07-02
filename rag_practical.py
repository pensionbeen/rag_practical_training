import os
import torch
from dotenv import load_dotenv
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

# 1. 한국어 지식 데이터 (Knowledge Data) 고정 선언
KNOWLEDGE = """Retrieval-Augmented Generation(검색 증강 생성) 또는 RAG는 정보 검색과 텍스트 생성을 결합하는 기술입니다. 언어 모델이 학습 중에 암기한 것에만 의존하는 대신, RAG 시스템은 먼저 문서 모음에서 관련 구절을 검색한 다음 해당 구절을 모델에 컨텍스트로 제공합니다. 이는 환각 현상(hallucination)을 줄이고 모델이 비공개 정보나 최신 정보에 대한 질문에 답변할 수 있도록 합니다.

RAG 파이프라인에는 두 가지 단계가 있습니다. 인덱싱(indexing) 단계에서는 문서를 로드하고, 작은 청크(chunk)로 분할하고, 임베딩 벡터로 변환하여 벡터 데이터베이스에 저장합니다. 질의(query) 단계에서는 사용자의 질문을 벡터로 변환하고, 가장 유사한 청크들을 검색한 다음, 이 청크들을 언어 모델에 전달하여 신뢰할 수 있는 답변을 생성합니다.

FAISS는 Facebook AI Similarity Search의 약자입니다. 임베딩 벡터를 저장하고 가장 유사한 벡터를 매우 빠르게 검색하는 오픈소스 라이브러리입니다. FAISS는 수백만 개의 벡터를 처리할 수 있으며 유사도 검색을 위해 가장 널리 사용되는 도구 중 하나입니다.

임베딩(embedding)은 텍스트의 의미를 나타내는 숫자 목록(벡터)입니다. 두 텍스트의 의미가 유사하면 임베딩 벡터 간의 거리도 가까워집니다. BGE(bge-small-en-v1.5)는 문장 임베딩을 생성하는 가볍고 빠른 모델입니다. 한국어 임베딩의 경우 ko-sroberta-multitask 같은 전용 모델이 널리 쓰입니다.

LangChain은 대형 언어 모델로 구동되는 애플리케이션을 구축하기 위한 프레임워크입니다. 개발자가 단 몇 줄의 코드만으로 이러한 구성 요소를 함께 연결할 수 있도록 문서 로더, 텍스트 분할기, 임베딩, 벡터 저장소, 검색기, 체인과 같은 빌딩 블록을 제공합니다."""

# 2. 텍스트 분할기 설정 (RecursiveCharacterTextSplitter)
# chunk_size=300, chunk_overlap=50
text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
docs = text_splitter.create_documents([KNOWLEDGE])

# 3. 한국어 임베딩 모델 설정 (jhgan/ko-sroberta-multitask)
print("Loading Korean Embedding Model ('jhgan/ko-sroberta-multitask')...")
embeddings = HuggingFaceEmbeddings(
    model_name="jhgan/ko-sroberta-multitask",
    encode_kwargs={"normalize_embeddings": True}
)

# 4. 로컬 FAISS 벡터 저장소 생성
print("Creating FAISS Vector Store...")
vectorstore = FAISS.from_documents(docs, embeddings)

# 5. 검색기(Retriever) 설정 (k=2)
retriever = vectorstore.as_retriever(search_kwargs={"k": 2})

# 6. 생성 LLM 모델 로드 (Gemini-2.5-Flash)
print("Connecting to Google Gemini API (gemini-2.5-flash)...")
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)


def ask(question: str):
    # 질문에 관련된 문서 검색
    retrieved_docs = retriever.invoke(question)
    
    # 검색된 문서를 컨텍스트 문자열로 결합
    context = "\n".join([doc.page_content for doc in retrieved_docs])
    
    # Prompt 작성
    prompt = f"""당신은 유용한 AI 어시스턴트입니다. 아래 제공된 참고 문서(Context)에 기반하여 질문(Question)에 대해 친절하게 한국어로 답변해 주세요.
참고 문서에 없는 내용이거나 답을 알 수 없다면 억지로 꾸며내지 말고 솔직하게 모른다고 대답해 주세요.

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
        print(f"\n[Chunk {idx}]")
        print(doc.page_content.strip())
    print("-" * 60)
    print(f"생성 답변 (Generated Answer):\n{answer}")
    print("=" * 60)
    
    return answer

if __name__ == "__main__":
    print("=" * 60)
    print("🤖 RAG 한국어 대화형 질의응답 시스템이 준비되었습니다!")
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
