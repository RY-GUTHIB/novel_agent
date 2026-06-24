"""tests/test_rag_fallback.py - RAG 降级模式单元测试"""

import sys
import tempfile
import os
from unittest.mock import patch
from novel_agent.core.rag import RAGStore


def test_normal_mode():
    """默认模式：向量 + BM25 均可初始化"""
    tmp = tempfile.mkdtemp()
    store = RAGStore(tmp)
    assert not store._vector_fallback
    store._init_client()
    assert store._collection is not None


def test_bm25_persist_independent():
    """BM25 持久化不依赖 ChromaDB"""
    tmp = tempfile.mkdtemp()
    store = RAGStore(tmp)
    store.add_chapter(1, "第一章", "这是第一章的内容。主角在青云宗修炼。")
    store.add_chapter(2, "第二章", "这是第二章的内容。主角突破到筑基。")

    # 重建 store 并跳过向量初始化，验证 BM25 可从 JSON 恢复
    store2 = RAGStore(tmp)
    store2._vector_fallback = True  # 模拟降级
    store2._init_bm25()
    assert store2._bm25 is not None
    assert len(store2._bm25_docs) >= 2


def test_add_and_search_bm25_only():
    """降级模式下写入后能通过 BM25 搜索"""
    tmp = tempfile.mkdtemp()
    store = RAGStore(tmp)
    store._vector_fallback = True  # 模拟嵌入模型不可用
    store.add_chapter(1, "第一章", "叶青云在青云宗修炼。")
    store.add_chapter(2, "第二章", "叶青云突破到筑基境。")
    store.add_chapter(3, "第三章", "王五在凡人界生活。")
    store.add_chapter(4, "第四章", "赵六是个普通人。")

    results = store.search("筑基", top_k=5, use_hybrid=False)
    assert len(results) >= 1
    assert any("筑基" in r["document"] for r in results)


def test_search_with_chapter_filter_fallback():
    """降级模式下章节过滤仍生效"""
    tmp = tempfile.mkdtemp()
    store = RAGStore(tmp)
    store._vector_fallback = True
    store.add_chapter(1, "第一章", "叶青云测试。")
    store.add_chapter(3, "第三章", "叶青云测试内容。")

    results = store.search("叶青云", top_k=5, filter_chapter_lt=3, use_hybrid=False)
    assert all(r["metadata"]["chapter"] < 3 for r in results)


def test_clear_cleans_bm25_persist():
    """clear() 应同时清理 BM25 持久化文件"""
    tmp = tempfile.mkdtemp()
    store = RAGStore(tmp)
    store._vector_fallback = True
    store.add_chapter(1, "第一章", "测试内容。")

    bm25_path = os.path.join(tmp, "bm25_index.json")
    assert os.path.exists(bm25_path)

    store.clear()
    assert not os.path.exists(bm25_path)


def test_collection_count_fallback():
    """降级模式下 get_collection_count 返回 BM25 文档数"""
    tmp = tempfile.mkdtemp()
    store = RAGStore(tmp)
    store._vector_fallback = True
    assert store.get_collection_count() == 0
    store.add_chapter(1, "第一章", "测试。")
    store._init_bm25()
    assert store.get_collection_count() >= 1


def test_add_outline_entry_fallback():
    """降级模式下 add_outline_entry 写入 BM25 但不写入 ChromaDB"""
    tmp = tempfile.mkdtemp()
    store = RAGStore(tmp)
    store._vector_fallback = True
    store.add_outline_entry("world_setting", "修真境界", "炼气、筑基、金丹...")
    store._init_bm25()
    assert len(store._bm25_docs) >= 1
    assert any("金丹" in d for d in store._bm25_docs)


def test_search_no_data():
    """无数据时搜索返回空列表"""
    tmp = tempfile.mkdtemp()
    store = RAGStore(tmp)
    store._vector_fallback = True
    results = store.search("任何", top_k=5, use_hybrid=False)
    assert results == []


def test_add_chapter_overwrite_fallback():
    """降级模式下重写同章节不崩溃"""
    tmp = tempfile.mkdtemp()
    store = RAGStore(tmp)
    store._vector_fallback = True
    store.add_chapter(1, "第一章", "旧版本叶青云。")
    store.add_chapter(2, "第二章", "正常章节张三。")
    store.add_chapter(1, "第一章", "新版本叶青云。")
    store.add_chapter(3, "第三章", "王五出现。")
    store.add_chapter(4, "第四章", "赵六闲逛。")
    # "张三" 在 5 篇文档中只出现 1 次，BM25 idf 为正
    results = store.search("张三", top_k=5, use_hybrid=False)
    assert len(results) >= 1


# ========== 真实降级触发测试 ==========

def test_real_fallback_on_embedding_failure():
    """嵌入模型加载失败时自动触发降级（不靠手动设置 _vector_fallback）"""
    tmp = tempfile.mkdtemp()
    store = RAGStore(tmp)
    with patch("novel_agent.core.rag.get_embedding_service") as mock_get, \
         patch("sys.stdin.isatty", return_value=True), \
         patch("builtins.input", return_value="y"):
        mock_get.side_effect = RuntimeError("模拟嵌入模型不可用")
        store._init_client()
    assert store._vector_fallback is True
    assert store._collection is None


def test_fallback_not_raised_to_caller():
    """嵌入模型失败时，用户确认降级后公共方法不抛异常"""
    tmp = tempfile.mkdtemp()
    store = RAGStore(tmp)
    with patch("novel_agent.core.rag.get_embedding_service") as mock_get, \
         patch("sys.stdin.isatty", return_value=True), \
         patch("builtins.input", return_value="y"):
        mock_get.side_effect = RuntimeError("模拟失败")
        store.add_chapter(1, "第一章", "叶青云在青云宗修炼。")
        store.add_chapter(2, "第二章", "叶青云突破到筑基境。")
        store.add_chapter(3, "第三章", "王五在凡人界生活。")
        store.add_chapter(4, "第四章", "赵六是个普通人。")
        results = store.search("筑基", top_k=5, use_hybrid=False)
    assert len(results) >= 1
    assert any("筑基" in r["document"] for r in results)


def test_fallback_rejected_raises():
    """用户拒绝降级时抛 RuntimeError"""
    import pytest
    tmp = tempfile.mkdtemp()
    store = RAGStore(tmp)
    with patch("novel_agent.core.rag.get_embedding_service") as mock_get, \
         patch("sys.stdin.isatty", return_value=True), \
         patch("builtins.input", return_value="n"):
        mock_get.side_effect = RuntimeError("模拟失败")
        with pytest.raises(RuntimeError):
            store._init_client()
    assert store._vector_fallback is False


def test_fallback_non_interactive_raises():
    """非交互模式（无 tty）下嵌入模型失败直接抛异常"""
    import pytest
    tmp = tempfile.mkdtemp()
    store = RAGStore(tmp)
    with patch("novel_agent.core.rag.get_embedding_service") as mock_get, \
         patch("sys.stdin.isatty", return_value=False):
        mock_get.side_effect = RuntimeError("模拟失败")
        with pytest.raises(RuntimeError):
            store._init_client()
    assert store._vector_fallback is False


# ========== writer 调用链集成测试 ==========

def test_writer_rag_context_pattern():
    """模拟 writer._get_rag_context 的搜索模式：summary 搜索 + 角色搜索 + 章节过滤"""
    tmp = tempfile.mkdtemp()
    store = RAGStore(tmp)
    store._vector_fallback = True
    store.add_chapter(5, "第五章", "叶青云在青云宗修炼，李四在一旁观看。")
    store.add_chapter(7, "第七章", "叶青云突破到筑基境，李四表示祝贺。")
    store.add_chapter(8, "第八章", "王五在凡人界生活。")
    store.add_chapter(10, "第十章", "赵六是个普通人。")

    chapter = 9
    summary = "突破筑基"

    # writer 的 _get_rag_context 执行模式
    rag_query = f"{summary} 的详细情节和设定"
    results = store.search(rag_query, filter_chapter_lt=chapter, top_k=5, use_hybrid=True)
    assert isinstance(results, list)

    for char in ["突破", "李四"]:
        char_results = store.search(
            f"{char} 给了 ...",
            filter_chapter_lt=chapter, filter_chapter_gte=max(1, chapter - 30), top_k=10,
        )
        assert isinstance(char_results, list)


def test_writer_finalize_chapter_pattern():
    """模拟 writer.finalize_chapter 调用的 add_chapter 不崩溃"""
    tmp = tempfile.mkdtemp()
    store = RAGStore(tmp)
    store._vector_fallback = True
    store.add_chapter(1, "第一章", "内容略。天地异象。")
    store.add_chapter(11, "第十一章", "本章正文内容。" * 100)
    store.add_chapter(12, "第十二章", "另一段剧情展开。")
    assert len(store._bm25_docs) >= 3
    # "天地异象" 只在第 1 章出现，idf 为正
    results = store.search("天地异象", top_k=3, use_hybrid=False)
    assert len(results) >= 1


def test_search_by_character_in_fallback():
    """search_by_character 在降级模式下正常工作"""
    tmp = tempfile.mkdtemp()
    store = RAGStore(tmp)
    store._vector_fallback = True
    store.add_chapter(1, "第一章", "叶青云出门历练。")
    store.add_chapter(2, "第二章", "叶青云遇到强敌。")
    store.add_chapter(3, "第三章", "张三路过。")
    store.add_chapter(4, "第四章", "李四吃饭。")
    # "张三" 在 4 篇中只出现 1 次，idf 为正
    results = store.search_by_character("张三", current_chapter=5, top_k=5)
    assert len(results) >= 1
    assert any("张三" in r for r in results)


def test_search_by_keyword_in_fallback():
    """search_by_keyword 在降级模式下正常工作"""
    tmp = tempfile.mkdtemp()
    store = RAGStore(tmp)
    store._vector_fallback = True
    store.add_chapter(1, "第一章", "神秘玉佩发出微光。")
    store.add_chapter(2, "第二章", "长剑出鞘声清脆。")
    store.add_chapter(3, "第三章", "丹药香气四溢。")
    results = store.search_by_keyword("玉佩", current_chapter=4, top_k=5)
    assert len(results) >= 1
