"""
rag_store.py - 向量数据库 + BM25 混合检索（Hybrid RAG）

使用 ChromaDB 本地向量库 + rank_bm25 关键词检索，
RRF（Reciprocal Rank Fusion）融合排序，
解决"第50章忘记第5章设定"的问题。

核心功能：
1. 存储：每章生成后，自动切片向量化存储 + BM25 索引更新
2. 检索：向量检索（语义相似）+ BM25（关键词精确匹配）→ RRF 融合
3. 检索维度：人物状态、地点描述、伏笔、时间线事件

嵌入模型：通过 embedding_service 统一管理 sentence_transformers
"""

import logging
import os
import re
import sys
from pathlib import Path
from typing import List, Dict

from .embedding_service import get_embedding_service

logger = logging.getLogger(__name__)


class RAGStore:
    """ChromaDB 向量存储 + BM25 关键词检索封装"""

    def __init__(self, persist_dir: str, top_k: int = 5, chunk_size: int = 500):
        self.persist_dir = str(Path(persist_dir) / "vector_db")
        self.top_k = top_k
        self.chunk_size = chunk_size
        self._client = None
        self._collection = None
        self._vector_fallback = False  # 嵌入模型不可用 → BM25-only 降级
        # BM25 相关（独立于 ChromaDB 持久化，降级时也可用）
        self._bm25_persist = str(Path(persist_dir) / "bm25_index.json")
        self._bm25 = None
        self._bm25_docs: List[str] = []
        self._bm25_metas: List[Dict] = []
        self._bm25_dirty = False  # 标记 BM25 需要重建（写时不重建，搜时按需重建）

    def _init_client(self):
        """懒加载 ChromaDB 客户端（嵌入模型不可用时提示用户确认降级）"""
        if self._client is not None:
            return
        if self._vector_fallback:
            # 已确认降级，跳过初始化
            return
        try:
            import chromadb
        except ImportError:
            raise ImportError("请先安装 chromadb: pip install chromadb>=0.5.0")

        # 使用项目内 embedding_service 管理的 sentence_transformers 模型（指向 vendor/models/ 本地路径）
        try:
            embedding_service = get_embedding_service(model_cache_dir=str(
                Path(__file__).parent.parent.parent / "vendor" / "models"
            ))
            model = embedding_service.get_model()
        except Exception as e:
            logger.warning("嵌入模型加载失败: %s", e)
            print(f"\n[警告] 嵌入模型不可用，向量检索功能受限。", file=sys.stderr)
            print(f"  错误: {e}", file=sys.stderr)
            if sys.stdin.isatty():
                answer = input("是否降级为 BM25-only 模式（仅关键词检索）？(y/N): ").strip().lower()
                if answer in ("y", "yes"):
                    self._vector_fallback = True
                    print("  已降级为 BM25-only 模式。\n")
                    return
            raise RuntimeError(
                f"嵌入模型加载失败，用户取消降级。\n"
                f"请检查 vendor/models/bge-small-zh-v1.5 模型文件是否完整。\n"
                f"错误详情: {e}"
            )

        # 包装为 ChromaDB 兼容的 embedding function
        class ProjectEmbeddingFunction:
            def __init__(self, mn: str):
                self._name = f"project_{mn}"
            def name(self) -> str:
                return self._name
            def __call__(self, input: List[str]) -> List[List[float]]:
                embeddings = model.encode(input, normalize_embeddings=True)
                return embeddings.tolist()
            def embed_query(self, input: str) -> List[float]:
                embedding = model.encode(input, normalize_embeddings=True)
                return embedding.tolist()
            def embed_document(self, input: str) -> List[float]:
                embedding = model.encode(input, normalize_embeddings=True)
                return embedding.tolist()

        self._embedding_fn = ProjectEmbeddingFunction(embedding_service.model_name)
        self._client = chromadb.PersistentClient(path=self.persist_dir)
        self._collection = self._client.get_or_create_collection(
            name="novel_chunks",
            metadata={"hnsw:space": "cosine"},
            embedding_function=self._embedding_fn,
        )

    def _init_bm25(self):
        """懒加载 BM25 索引（从 JSON 持久化文件读取，不依赖 ChromaDB）"""
        if self._bm25 is not None and not self._bm25_dirty:
            return
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            raise ImportError("请先安装 rank_bm25: pip install rank_bm25")

        # 优先从持久化文件加载
        bm25_path = Path(self._bm25_persist)
        if bm25_path.exists() and self._bm25 is None:
            try:
                import json
                with open(bm25_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._bm25_docs = data.get("docs", [])
                self._bm25_metas = data.get("metas", [])
                if self._bm25_docs:
                    tokenized = [self._tokenize(d) for d in self._bm25_docs]
                    self._bm25 = BM25Okapi(tokenized)
                self._bm25_dirty = False
                return
            except Exception as e:
                logger.warning("BM25 持久化文件加载失败，尝试从 ChromaDB 重建: %s", e)

        # 回退：从 ChromaDB 全量重建
        if not self._vector_fallback:
            self._init_client()
            try:
                if self._collection is None:
                    raise RuntimeError("ChromaDB 不可用")
                all_data = self._collection.get()
                if all_data and all_data.get("documents"):
                    self._bm25_docs = list(all_data["documents"])
                    self._bm25_metas = list(all_data["metadatas"]) if all_data.get("metadatas") else []
                    tokenized = [self._tokenize(d) for d in self._bm25_docs]
                    self._bm25 = BM25Okapi(tokenized)
                    self._bm25_dirty = False
                    self._save_bm25()
                return
            except Exception as e:
                logger.warning("从 ChromaDB 重建 BM25 失败: %s", e)

        # 都不可用 → 空索引
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

    def _save_bm25(self):
        """将 BM25 文档/元数据持久化到 JSON 文件（独立于 ChromaDB）"""
        import json
        try:
            Path(self._bm25_persist).parent.mkdir(parents=True, exist_ok=True)
            with open(self._bm25_persist, "w", encoding="utf-8") as f:
                json.dump({"docs": self._bm25_docs, "metas": self._bm25_metas}, f,
                          ensure_ascii=False, indent=1)
        except Exception as e:
            logger.warning("BM25 持久化写入失败: %s", e)

    def add_chapter(self, chapter_num: int, chapter_title: str, content: str):
        """
        将章节内容切片并存入向量库 + 更新 BM25 索引
        同一章节多次调用会覆盖（先删旧 ID 再添加）
        """
        self._init_client()

        chunks = self._chunk_text(content)
        if not chunks:
            return

        # 向量存储（可用时）
        if not self._vector_fallback and self._collection is not None:
            # 先删同章节旧数据（覆盖写入）
            try:
                existing_ids = self._collection.get(
                    where={"chapter": chapter_num},
                    include=[],
                )
                if existing_ids and existing_ids.get("ids"):
                    self._collection.delete(ids=existing_ids["ids"])
            except (ValueError, KeyError):
                pass  # 首次写入无旧数据时 ChromaDB 可能抛此类异常

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

        # BM25 索引始终更新（独立于向量存储）
        metadatas = [
            {"chapter": chapter_num, "title": chapter_title,
             "chunk_index": i, "type": "chapter_content"}
            for i in range(len(chunks))
        ]
        self._bm25_docs.extend(chunks)
        self._bm25_metas.extend(metadatas)
        self._bm25_dirty = True
        self._save_bm25()

    def add_outline_entry(self, entry_type: str, title: str, content: str):
        """存储大纲/设定条目"""
        self._init_client()
        if not self._vector_fallback and self._collection is not None:
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
        # BM25 同步
        self._bm25_docs.append(content)
        self._bm25_metas.append({"chapter": -1, "title": title, "type": entry_type})
        self._bm25_dirty = True
        self._save_bm25()

    def search(self, query: str, top_k: int = None,
               filter_chapter_lt: int = None,
               filter_chapter_gte: int = None,
               use_hybrid: bool = True) -> List[Dict]:
        """
        混合检索：向量 + BM25 → RRF 融合
        嵌入模型不可用时自动降级为 BM25-only
        """
        if top_k is None:
            top_k = self.top_k
        self._init_client()

        where_clause = None
        if filter_chapter_gte is not None and filter_chapter_lt is not None:
            where_clause = {"$and": [
                {"chapter": {"$gte": filter_chapter_gte}},
                {"chapter": {"$lt": filter_chapter_lt}},
            ]}
        elif filter_chapter_lt is not None:
            where_clause = {"chapter": {"$lt": filter_chapter_lt}}
        elif filter_chapter_gte is not None:
            where_clause = {"chapter": {"$gte": filter_chapter_gte}}

        # 向量检索（降级时跳过）
        vec_hits = {}
        if not self._vector_fallback and self._collection is not None:
            vec_results = self._collection.query(
                query_texts=[query],
                n_results=top_k * 2,
                where=where_clause,
            )
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
        if use_hybrid or self._vector_fallback:
            self._init_bm25()
            if self._bm25 is not None:
                tokenized_query = self._tokenize(query)
                bm25_scores = self._bm25.get_scores(tokenized_query)
                scored = sorted(enumerate(bm25_scores), key=lambda x: -x[1])[:top_k * 2]
                for rank, (idx, score) in enumerate(scored):
                    if score <= 0:
                        continue
                    meta = self._bm25_metas[idx] if idx < len(self._bm25_metas) else {}
                    if filter_chapter_lt is not None or filter_chapter_gte is not None:
                        ch = meta.get("chapter", -1)
                        if (filter_chapter_lt is not None and ch >= filter_chapter_lt) or \
                           (filter_chapter_gte is not None and ch < filter_chapter_gte):
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
                             top_k: int = None) -> List[str]:
        if top_k is None:
            top_k = self.top_k
        query = f"{character_name} 的言行 状态 经历"
        results = self.search(query, top_k=top_k,
                             filter_chapter_lt=current_chapter)
        return [r["document"] for r in results]

    def search_by_location(self, location_name: str,
                            current_chapter: int,
                            top_k: int = None) -> List[str]:
        if top_k is None:
            top_k = self.top_k
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

    def _chunk_text(self, text: str, chunk_size: int = None) -> List[str]:
        if chunk_size is None:
            chunk_size = self.chunk_size
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
        """清空向量库和 BM25 持久化"""
        import shutil
        import os
        # 先释放 ChromaDB 连接
        self._client = None
        self._collection = None
        if os.path.exists(self.persist_dir):
            for retry in range(3):
                try:
                    shutil.rmtree(self.persist_dir)
                    break
                except PermissionError:
                    import time
                    time.sleep(0.5)
        # 清空 BM25 持久化
        bm25_path = Path(self._bm25_persist)
        if bm25_path.exists():
            try:
                bm25_path.unlink()
            except Exception:
                pass
        self._bm25 = None
        self._bm25_docs = []
        self._bm25_metas = []
        self._bm25_dirty = False

    def get_collection_count(self) -> int:
        """获取已存储片段数量"""
        self._init_client()
        if self._vector_fallback or self._collection is None:
            return len(self._bm25_docs) if self._bm25 is not None else 0
        return self._collection.count()

