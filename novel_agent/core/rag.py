"""
rag_store.py - 向量数据库 + BM25 混合检索（Hybrid RAG）

使用 ChromaDB 本地向量库 + rank_bm25 关键词检索，
RRF（Reciprocal Rank Fusion）融合排序，
解决"第50章忘记第5章设定"的问题。

核心功能：
1. 存储：每章生成后，自动切片向量化存储 + BM25 索引更新
2. 检索：向量检索（语义相似）+ BM25（关键词精确匹配）→ RRF 融合
3. 检索维度：人物状态、地点描述、伏笔、时间线事件
"""

import os
import re
import config
from pathlib import Path
from typing import List, Dict


class RAGStore:
    """ChromaDB 向量存储 + BM25 关键词检索封装"""

    def __init__(self, persist_dir: str = None, model_cache_dir: str = None):
        self.persist_dir = str(Path(persist_dir or config.DATA_DIR) / "vector_db")
        # 模型缓存目录（换电脑时只需复制此目录，避免重新下载）
        model_cache = Path(model_cache_dir or config.DATA_DIR) / "models" / "sentence-transformers"
        model_cache.mkdir(parents=True, exist_ok=True)
        os.environ["SENTENCE_TRANSFORMERS_HOME"] = str(model_cache)
        self._client = None
        self._collection = None
        # BM25 相关
        self._bm25 = None
        self._bm25_docs: List[str] = []
        self._bm25_metas: List[Dict] = []
        self._bm25_dirty = False  # 标记 BM25 需要重建（写时不重建，搜时按需重建）

    def _init_client(self):
        """懒加载 ChromaDB 客户端"""
        if self._client is not None:
            return
        try:
            import chromadb
            from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        except ImportError:
            raise ImportError("请先安装 chromadb: pip install chromadb>=0.5.0")

        # 使用对中文支持更好的嵌入模型
        self._embedding_fn = SentenceTransformerEmbeddingFunction(
            model_name="BAAI/bge-small-zh-v1.5",
        )
        self._client = chromadb.PersistentClient(path=self.persist_dir)
        self._collection = self._client.get_or_create_collection(
            name="novel_chunks",
            metadata={"hnsw:space": "cosine"},
            embedding_function=self._embedding_fn,
        )

    def _init_bm25(self):
        """懒加载 BM25 索引（按需重建，不阻塞写入路径）"""
        if self._bm25 is not None and not self._bm25_dirty:
            return
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            raise ImportError("请先安装 rank_bm25: pip install rank_bm25")

        # 从 ChromaDB 全量重建 BM25 索引
        self._init_client()
        try:
            all_data = self._collection.get()
            if all_data and all_data.get("documents"):
                self._bm25_docs = list(all_data["documents"])
                self._bm25_metas = list(all_data["metadatas"]) if all_data.get("metadatas") else []
                tokenized = [self._tokenize(d) for d in self._bm25_docs]
                self._bm25 = BM25Okapi(tokenized)
                self._bm25_dirty = False
        except Exception:
            self._bm25_docs = []
            self._bm25_metas = []
            self._bm25 = None

    def _tokenize(self, text: str) -> List[str]:
        """中文分词（简单字符级 + 2-gram）"""
        # 保留中文字符和英文单词
        tokens = []
        # 按非中英文分割
        parts = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+', text)
        for part in parts:
            if re.match(r'[\u4e00-\u9fff]+', part):
                # 中文：单字 + 2-gram
                tokens.extend(list(part))
                for i in range(len(part) - 1):
                    tokens.append(part[i:i+2])
            else:
                tokens.append(part.lower())
        return tokens

    def add_chapter(self, chapter_num: int, chapter_title: str, content: str):
        """
        将章节内容切片并存入向量库 + 更新 BM25 索引
        同一章节多次调用会覆盖（先删旧 ID 再添加）
        """
        self._init_client()

        # 先删同章节旧数据（覆盖写入）
        try:
            existing_ids = self._collection.get(
                where={"chapter": chapter_num},
                include=[],
            )
            if existing_ids and existing_ids.get("ids"):
                self._collection.delete(ids=existing_ids["ids"])
        except Exception:
            pass  # 首次写入无旧数据

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

        batch_size = 100
        for start in range(0, len(chunks), batch_size):
            end = start + batch_size
            self._collection.add(
                ids=ids[start:end],
                documents=chunks[start:end],
                metadatas=metadatas[start:end],
            )

        # 标记 BM25 为脏，检索时按需重建（不阻塞写入路径）
        self._bm25_dirty = True

    def add_outline_entry(self, entry_type: str, title: str, content: str):
        """存储大纲/设定条目"""
        self._init_client()
        chunk_id = f"{entry_type}_{title}"
        self._collection.add(
            ids=[chunk_id],
            documents=[content],
            metadatas=[{
                "chapter": -1,
                "title": title,
                "type": entry_type,
            }],
        )
        self._bm25_dirty = True

    def search(self, query: str, top_k: int = config.RAG_TOP_K,
               filter_chapter_lt: int = None,
               use_hybrid: bool = True) -> List[Dict]:
        """
        混合检索：向量 + BM25 → RRF 融合
        """
        self._init_client()

        where_clause = None
        if filter_chapter_lt is not None:
            where_clause = {"chapter": {"$lt": filter_chapter_lt}}

        # 向量检索
        vec_results = self._collection.query(
            query_texts=[query],
            n_results=top_k * 2,  # 多取一些给融合用
            where=where_clause,
        )

        vec_hits = {}
        if vec_results and vec_results["ids"]:
            for i, doc_id in enumerate(vec_results["ids"][0]):
                vec_hits[doc_id] = {
                    "document": vec_results["documents"][0][i],
                    "metadata": vec_results["metadatas"][0][i],
                    "distance": vec_results["distances"][0][i],
                    "rank": i + 1,
                }

        # BM25 关键词检索
        bm25_hits = {}
        if use_hybrid:
            self._init_bm25()
            if self._bm25 is not None:
                tokenized_query = self._tokenize(query)
                bm25_scores = self._bm25.get_scores(tokenized_query)
                # 取 top 2k
                scored = sorted(enumerate(bm25_scores), key=lambda x: -x[1])[:top_k * 2]
                for rank, (idx, score) in enumerate(scored):
                    if score <= 0:
                        continue
                    meta = self._bm25_metas[idx] if idx < len(self._bm25_metas) else {}
                    # 如果有章节过滤
                    if filter_chapter_lt is not None:
                        ch = meta.get("chapter", -1)
                        if ch >= filter_chapter_lt:
                            continue
                    doc_id = f"bm25_{idx}"
                    bm25_hits[doc_id] = {
                        "document": self._bm25_docs[idx],
                        "metadata": meta,
                        "bm25_score": float(score),
                        "rank": rank + 1,
                    }

        # RRF 融合
        if bm25_hits:
            merged = self._rrf_fusion(vec_hits, bm25_hits, top_k)
        else:
            # 无 BM25，直接用向量结果
            merged = sorted(vec_hits.values(), key=lambda x: x["rank"])[:top_k]

        # 格式化输出
        output = []
        for hit in merged:
            output.append({
                "document": hit["document"],
                "metadata": hit["metadata"],
                "distance": hit.get("distance", 1.0),
            })
        return output

    def _rrf_fusion(self, vec_hits: Dict, bm25_hits: Dict,
                     top_k: int, k: int = 60) -> List[Dict]:
        """
        RRF (Reciprocal Rank Fusion) 融合向量检索和 BM25 检索结果。
        公式：score = sum(1 / (k + rank_i))
        """
        scores = {}

        for doc_id, hit in vec_hits.items():
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + hit["rank"])

        for doc_id, hit in bm25_hits.items():
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + hit["rank"])

        # 按分数排序
        sorted_ids = sorted(scores.keys(), key=lambda x: -scores[x])[:top_k]

        results = []
        for doc_id in sorted_ids:
            if doc_id in vec_hits:
                results.append(vec_hits[doc_id])
            elif doc_id in bm25_hits:
                results.append(bm25_hits[doc_id])

        return results

    def search_by_character(self, character_name: str,
                             current_chapter: int,
                             top_k: int = config.RAG_TOP_K) -> List[str]:
        query = f"{character_name} 的言行 状态 经历"
        results = self.search(query, top_k=top_k,
                             filter_chapter_lt=current_chapter)
        return [r["document"] for r in results]

    def search_by_location(self, location_name: str,
                           current_chapter: int,
                           top_k: int = config.RAG_TOP_K) -> List[str]:
        query = f"{location_name} 地点 场景 描述"
        results = self.search(query, top_k=top_k,
                             filter_chapter_lt=current_chapter)
        return [r["document"] for r in results]

    def search_by_keyword(self, keyword: str,
                          current_chapter: int,
                          top_k: int = 5) -> List[str]:
        """精确关键词检索（仅 BM25），用于查找专有名词"""
        self._init_bm25()
        if self._bm25 is None:
            return []
        tokenized = self._tokenize(keyword)
        scores = self._bm25.get_scores(tokenized)
        scored = sorted(enumerate(scores), key=lambda x: -x[1])[:top_k]
        results = []
        for idx, score in scored:
            if score <= 0:
                continue
            meta = self._bm25_metas[idx] if idx < len(self._bm25_metas) else {}
            if meta.get("chapter", -1) >= current_chapter:
                continue
            results.append(self._bm25_docs[idx])
        return results

    def _chunk_text(self, text: str, chunk_size: int = config.RAG_CHUNK_SIZE) -> List[str]:
        """智能切片：按段落分割"""
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
        """清空向量库"""
        import shutil
        import os
        if os.path.exists(self.persist_dir):
            shutil.rmtree(self.persist_dir)
        self._client = None
        self._collection = None
        self._bm25 = None
        self._bm25_docs = []
        self._bm25_metas = []
        self._bm25_dirty = False

    def get_collection_count(self) -> int:
        """获取已存储片段数量"""
        self._init_client()
        return self._collection.count()

