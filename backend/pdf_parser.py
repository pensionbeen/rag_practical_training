import os
from typing import List
import fitz  # PyMuPDF
from langchain_text_splitters import RecursiveCharacterTextSplitter

def parse_pdf_to_chunks(file_source, chunk_size: int = 300, chunk_overlap: int = 50) -> List[str]:
    """
    PyMuPDF(fitz)를 이용하여 PDF 파일(경로 또는 파일 객체)을 로드하고,
    문맥을 보존하는 청킹 규칙을 적용한 텍스트 리스트(List[str])를 반환합니다.
    """
    if isinstance(file_source, str):
        if not os.path.exists(file_source):
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_source}")
        file_basename = os.path.basename(file_source)
        doc = fitz.open(file_source)
    else:
        # 파일 객체인 경우 (BytesIO 등)
        if hasattr(file_source, "seek"):
            file_source.seek(0)
        file_bytes = file_source.read()
        file_basename = getattr(file_source, "name", "document.pdf")
        file_basename = os.path.basename(file_basename)
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        
    parsed_chunks = []
    
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, 
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""]
    )
    
    for page_idx, page in enumerate(doc):
        text = page.get_text()
        if not text or not text.strip():
            continue
            
        # 페이지별 텍스트 청킹
        page_chunks = text_splitter.split_text(text)
        
        for chunk in page_chunks:
            # 문맥 보존을 위해 파일 이름 및 페이지 정보 기입
            context_preserved_chunk = f"[{file_basename} - Page {page_idx + 1}] {chunk.strip()}"
            parsed_chunks.append(context_preserved_chunk)
            
    doc.close()
    return parsed_chunks
