"""
rag_store.py - 向量数据库（RAG检索增强）

使用 ChromaDB 本地向量库，为长篇小说提供语义检索能力。
解决"第50章忘记第5章设定"的问题。

核心功能：
1. 存储：每章生成后，自动切片向量化存储
2. 检索：生成新章前，语义检索相关前文片段注入prompt
3. 检索维度：人物状态、地点描述、伏笔、时间线事件
"""

import json
import re
from pathlib import Path
from typing import List, Dict

from config import DATA_DIR, RAG_TOP_K, RAG_CHUNK_SIZE


class RAGStore:
    """ChromaDB 向量存储封装"""

    def __init__(self, persist_dir: str = None):
        self.persist_dir = str(Path(persist_dir or DATA_DIR) / "vector_db")
        self._client = None
        self._collection = None

    def _init_client(self):
        """懒加载 ChromaDB 客户端"""
        if self._client is not None:
            return
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError:
            raise ImportError("请先安装 chromadb: pip install chromadb>=0.5.0")

        self._client = chromadb.PersistentClient(path=self.persist_dir)
        self._collection = self._client.get_or_create_collection(
            name="novel_chunks",
            metadata={"hnsw:space": "cosine"},
        )

    def add_chapter(self, chapter_num: int, chapter_title: str, content: str):
        """
        将章节内容切片并存入向量库
        :param chapter_num: 章节号
        :param chapter_title: 章节标题
        :param content: 章节正文
        """
        self._init_client()
        chunks = self._chunk_text(content)
        if not chunks:
            return

        ids = [f"ch{chapter_num}_chunk{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "chapter": chapter_num,
                "title": chapter_title,
                "chunk_index": i,
                "type": "chapter_content",
            }
            for i in range(len(chunks))
        ]

        # ChromaDB 支持批量添加
        batch_size = 100
        for start in range(0, len(chunks), batch_size):
            end = start + batch_size
            self._collection.add(
                ids=ids[start:end],
                documents=chunks[start:end],
                metadatas=metadatas[start:end],
            )

    def add_outline_entry(self, entry_type: str, title: str, content: str):
        """
        存储大纲/设定条目（人物档案、地点描述、世界观）
        :param entry_type: "character" | "location" | "world_setting" | "foreshadow"
        :param title: 条目名称
        :param content: 条目内容
        """
        self._init_client()
        chunk_id = f"{entry_type}_{title}"
        self._collection.add(
            ids=[chunk_id],
            documents=[content],
            metadatas=[{
                "chapter": -1,  # 大纲类无章节号
                "title": title,
                "type": entry_type,
            }],
        )

    def search(self, query: str, top_k: int = RAG_TOP_K,
               filter_chapter_lt: int = None) -> List[Dict]:
        """
        语义检索相关片段
        :param query: 查询文本（通常是当前章节大纲/涉及人物）
        :param top_k: 返回结果数量
        :param filter_chapter_lt: 仅检索此章节号之前的片段（避免剧透）
        :return: [{"document": "...", "metadata": {...}, "distance": 0.xx}, ...]
        """
        self._init_client()

        where_clause = None
        if filter_chapter_lt is not None:
            where_clause = {"chapter": {"$lt": filter_chapter_lt}}

        results = self._collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where_clause,
        )

        # 格式化输出
        output = []
        if results and results["ids"]:
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                output.append({
                    "document": doc,
                    "metadata": meta,
                    "distance": dist,  # 越小越相关
                })
        return output

    def search_by_character(self, character_name: str,
                             current_chapter: int,
                             top_k: int = RAG_TOP_K) -> List[str]:
        """检索某人物相关的历史片段（用于注入prompt）"""
        query = f"{character_name} 的言行 状态 经历"
        results = self.search(query, top_k=top_k,
                             filter_chapter_lt=current_chapter)
        return [r["document"] for r in results]

    def search_by_location(self, location_name: str,
                           current_chapter: int,
                           top_k: int = RAG_TOP_K) -> List[str]:
        """检索某地点相关的历史描述"""
        query = f"{location_name} 地点 场景 描述"
        results = self.search(query, top_k=top_k,
                             filter_chapter_lt=current_chapter)
        return [r["document"] for r in results]

    def _chunk_text(self, text: str, chunk_size: int = RAG_CHUNK_SIZE) -> List[str]:
        """
        智能切片：按段落分割，尽量保持语义完整
        """
        # 按段落分割
        paragraphs = re.split(r'\n\s*\n', text)
        chunks = []
        current_chunk = ""
        current_len = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            para_len = len(para)

            if current_len + para_len <= chunk_size:
                current_chunk += para + "\n\n"
                current_len += para_len
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = para + "\n\n"
                current_len = para_len

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

    def clear(self):
        """清空向量库（重新开始小说时用）"""
        import shutil
        import os
        if os.path.exists(self.persist_dir):
            shutil.rmtree(self.persist_dir)
        self._client = None
        self._collection = None

    def get_collection_count(self) -> int:
        """获取已存储片段数量"""
        self._init_client()
        return self._collection.count()
