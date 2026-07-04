from langchain_core.documents import Document

from backend.utils import filter_docs_by_relevance as _filter_docs_by_relevance
from backend.utils import sanitize_category_path as _sanitize_category_path


def _doc(source):
    return Document(page_content="content", metadata={"source": source})


def test_filters_out_docs_below_threshold():
    docs_with_scores = [
        (_doc("a.md"), 0.9),
        (_doc("b.md"), 0.5),
        (_doc("c.md"), 0.7),
    ]
    result = _filter_docs_by_relevance(docs_with_scores, threshold=0.7)
    assert [d.metadata["source"] for d in result] == ["a.md", "c.md"]


def test_keeps_all_docs_when_threshold_is_zero():
    docs_with_scores = [(_doc("a.md"), 0.1), (_doc("b.md"), 0.0)]
    result = _filter_docs_by_relevance(docs_with_scores, threshold=0.0)
    assert len(result) == 2


def test_drops_all_docs_when_threshold_is_above_every_score():
    docs_with_scores = [(_doc("a.md"), 0.5), (_doc("b.md"), 0.6)]
    result = _filter_docs_by_relevance(docs_with_scores, threshold=0.9)
    assert result == []


def test_sanitize_category_path_blocks_traversal(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    target = _sanitize_category_path("../../etc/passwd", vault).resolve()
    vault_resolved = vault.resolve()
    assert target == vault_resolved or vault_resolved in target.parents


def test_sanitize_category_path_keeps_nested_category(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    target = _sanitize_category_path("인공지능/딥러닝", vault)
    assert target == vault / "인공지능" / "딥러닝"


def test_sanitize_category_path_strips_drive_letter(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    target = _sanitize_category_path("C:/Windows/System32", vault).resolve()
    vault_resolved = vault.resolve()
    assert target == vault_resolved or vault_resolved in target.parents
