"""
main.py와 분리된 순수 로직 헬퍼 모음.

임베딩/LLM 초기화 등 무거운 모듈 레벨 부작용이 없어서, 테스트에서 가볍게 임포트해 쓸 수 있다.
"""
import re
from pathlib import Path

from langchain_core.documents import Document


def filter_docs_by_relevance(
    docs_with_scores: list[tuple[Document, float]], threshold: float
) -> list[Document]:
    """관련성 점수가 threshold 미만인 문서를 제외한다 (동떨어진 질문에도 예전 논문이 계속 노출되는 문제 방지)."""
    return [doc for doc, score in docs_with_scores if score >= threshold]


def sanitize_category_path(category: str, vault: Path) -> Path:
    """
    사용자/LLM이 제공한 카테고리 문자열을 볼트 내부의 안전한 하위 경로로 정규화한다.
    구분자(/,\\)로 나눈 뒤 각 조각을 개별적으로 새니타이즈하여, '..'나 절대 경로를 통한
    볼트 바깥 경로 순회(path traversal)를 막는다.
    """
    segments = re.split(r'[\\/]+', category.strip())
    safe_segments = []
    for seg in segments:
        seg = re.sub(r'[*?:"<>|]', "", seg).strip()
        if not seg or seg in (".", ".."):
            continue
        safe_segments.append(seg)

    target_dir = vault.joinpath(*safe_segments) if safe_segments else vault

    resolved_vault = vault.resolve()
    resolved_target = target_dir.resolve()
    if resolved_target != resolved_vault and resolved_vault not in resolved_target.parents:
        return vault

    return target_dir
