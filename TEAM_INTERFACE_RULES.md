# 🤝 Obsidian-RAG 팀 개발 인터페이스 규칙 (협업 계약서)

본 프로젝트는 내부 구현(로직)에 서로 간섭하지 않는 '블랙박스 개발 원칙'을 따릅니다. 단, 각 모듈 간 통신 시 아래의 **입출력 데이터 형태(Interface)**는 반드시 엄수하십시오.

## 1. [Data Parsing 파트] -> [Core RAG 파트]
* **입력 규격:** 논문 등 파싱 결과를 반드시 순수 텍스트(String)가 담긴 **파이썬 리스트(List) 형태**로 넘겨야 합니다.
  * **예시:** `parsed_chunks = ["AI의 기본 개념은...", "아이돌 산업은..."]`

## 2. [Frontend 파트] <-> [Core RAG 파트] API 통신 규격
프론트엔드는 반드시 아래의 목적지 주소(Endpoint)와 HTTP Method 규격을 준수하여 백엔드에 요청을 보내야 합니다.

* **[기능 1] 질문 전송 (Q&A)**
  * **Endpoint:** `POST /api/v1/ask`
  * **요청 (Request):** 사용자의 질문을 `{"query": "질문 텍스트"}` 형태의 JSON으로 전송합니다.
  * **응답 (Response):** 성공 시 `200 OK`와 함께 `{"response": "답변", "source_file": "파일명.md"}`을 반환합니다.
* **[기능 2] 복습 노트 전송 (Save)**
  * **Endpoint:** `POST /api/v1/obsidian/save`
  * **요청 (Request):** `{"question": "질문", "answer": "답변"}` 형태의 JSON으로 전송합니다.
  * **응답 (Response):** 정상 저장 시 `201 Created`를 반환하며, 데이터 누락 시 `400 Bad Request`를 반환합니다.