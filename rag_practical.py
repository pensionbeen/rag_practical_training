import torch
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

# 1. 지식 데이터 (Knowledge Data) 고정 선언
KNOWLEDGE = """Retrieval-Augmented Generation, or RAG, is a technique that combines information retrieval with text generation. Instead of relying only on what a language model memorized during training, a RAG system first searches a collection of documents for relevant passages and then gives those passages to the model as context. This reduces hallucination and lets the model answer questions about private or up-to-date information.

A RAG pipeline has two phases. In the indexing phase, documents are loaded, split into small chunks, converted into embedding vectors, and stored in a vector database. In the query phase, the user question is turned into a vector, the most similar chunks are retrieved, and those chunks are passed to the language model to generate a grounded answer.

FAISS stands for Facebook AI Similarity Search. It is an open-source library that stores embedding vectors and searches for the most similar ones very quickly. FAISS can handle millions of vectors and is one of the most widely used tools for similarity search.

An embedding is a list of numbers that represents the meaning of a piece of text. When two texts have a similar meaning, their embedding vectors are close to each other. BGE (bge-small-en-v1.5) is a small and fast model that creates sentence embeddings.

LangChain is a framework for building applications powered by large language models. It provides building blocks such as document loaders, text splitters, embeddings, vector stores, retrievers, and chains, so developers can connect these pieces together with only a few lines of code."""

# 2. 텍스트 분할기 설정 (RecursiveCharacterTextSplitter)
# chunk_size=300, chunk_overlap=50
text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
docs = text_splitter.create_documents([KNOWLEDGE])

# 3. 임베딩 모델 설정 (BAAI/bge-small-en-v1.5)
# encode_kwargs={"normalize_embeddings": True}
print("Loading Embedding Model ('BAAI/bge-small-en-v1.5')...")
embeddings = HuggingFaceEmbeddings(
    model_name="BAAI/bge-small-en-v1.5",
    encode_kwargs={"normalize_embeddings": True}
)

# 4. 로컬 FAISS 벡터 저장소 생성
print("Creating FAISS Vector Store...")
vectorstore = FAISS.from_documents(docs, embeddings)

# 5. 검색기(Retriever) 설정 (k=2)
retriever = vectorstore.as_retriever(search_kwargs={"k": 2})

# 6. 생성 LLM 모델 로드 (google/flan-t5-base)
print("Loading LLM Model ('google/flan-t5-base')...")
model_name = "google/flan-t5-base"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSeq2SeqLM.from_pretrained(model_name)

# GPU 사용 가능 시 가속 설정
device = "cuda" if torch.cuda.is_available() else "cpu"
model = model.to(device)

def ask(question: str):
    # 질문에 관련된 문서 검색
    retrieved_docs = retriever.invoke(question)
    
    # 검색된 문서를 컨텍스트 문자열로 결합
    context = "\n".join([doc.page_content for doc in retrieved_docs])
    
    # Prompt 작성
    prompt = f"Answer the following question based on the provided context.\n\nContext:\n{context}\n\nQuestion: {question}\n\nAnswer:"
    
    # 토큰화 및 디바이스 이동
    inputs = tokenizer(prompt, return_tensors="pt").to(device)
    
    # 답변 생성
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=150,
            temperature=0.0,
            do_sample=False
        )
    
    # 결과 디코딩
    answer = tokenizer.decode(outputs[0], skip_special_tokens=True)
    
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
    # 7. ask() 함수 호출 및 결과 출력
    ask("What does FAISS stand for?")
