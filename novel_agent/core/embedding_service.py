"""
embedding_service.py - 本地嵌入模型服务

封装 sentence_transformers（PyTorch）或 onnxruntime（ONNX），
为 RAG 提供文本向量化能力。
默认使用 vendor/models/bge-small-zh-v1.5（本地离线）。
"""

import logging
import os
from pathlib import Path
from typing import List, Union
import numpy as np

logger = logging.getLogger(__name__)

try:
    from config import DEFAULT_EMBEDDING_MODEL as _cfg_model
    DEFAULT_MODEL_NAME = _cfg_model
except (ImportError, AttributeError):
    DEFAULT_MODEL_NAME = "BAAI/bge-small-zh-v1.5"

_instance = None

HF_ENDPOINT = os.environ.get("HF_ENDPOINT") or os.environ.get("HUGGINGFACE_HUB_URL")
if HF_ENDPOINT:
    os.environ.setdefault("HF_ENDPOINT", HF_ENDPOINT)

_BGE_QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


class _OnnxModel:
    """ONNX 推理封装，无需 torch，仅依赖 onnxruntime + tokenizers"""

    def __init__(self, model_dir: str):
        import json
        from tokenizers import Tokenizer, models
        import onnxruntime as ort

        model_path = Path(model_dir)
        onnx_path = model_path / "onnx" / "model.onnx"

        # 加载 tokenizer（不用 transformers，避免 torch 依赖）
        self.tokenizer = Tokenizer.from_file(str(model_path / "tokenizer.json"))
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]", length=512)
        self.tokenizer.enable_truncation(max_length=512)

        self.session = ort.InferenceSession(str(onnx_path))
        self._dim = 512

        # 读取 pooling 配置
        pool_cfg_path = model_path / "1_Pooling" / "config.json"
        if pool_cfg_path.exists():
            with open(pool_cfg_path) as f:
                pool_cfg = json.load(f)
            self._pooling_mode = pool_cfg.get("pooling_mode", "cls")
        else:
            self._pooling_mode = "cls"

    def get_embedding_dimension(self) -> int:
        return self._dim

    def encode(self, texts: List[str], normalize_embeddings: bool = True,
               show_progress_bar: bool = False, batch_size: int = 32) -> np.ndarray:
        if isinstance(texts, str):
            texts = [texts]
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]

            # tokenizers 编码
            encoded = self.tokenizer.encode_batch(batch)
            max_len = max(len(e.ids) for e in encoded)
            batch_size_actual = len(encoded)

            input_ids = np.zeros((batch_size_actual, max_len), dtype=np.int64)
            attention_mask = np.zeros((batch_size_actual, max_len), dtype=np.int64)
            token_type_ids = np.zeros((batch_size_actual, max_len), dtype=np.int64)

            for j, e in enumerate(encoded):
                length = len(e.ids)
                input_ids[j, :length] = e.ids
                attention_mask[j, :length] = e.attention_mask
                tt = e.type_ids
                if tt:
                    token_type_ids[j, :length] = tt

            ort_inputs = {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids,
            }
            outputs = self.session.run(None, ort_inputs)
            last_hidden = outputs[0]

            # CLS pooling
            if self._pooling_mode == "cls":
                embeddings = last_hidden[:, 0, :]
            else:
                mask = np.expand_dims(attention_mask, axis=-1).astype(float)
                embeddings = (last_hidden * mask).sum(axis=1) / mask.sum(axis=1)

            if normalize_embeddings:
                norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
                norms = np.where(norms == 0, 1e-12, norms)
                embeddings = embeddings / norms

            all_embeddings.append(embeddings)

        return np.concatenate(all_embeddings, axis=0)


class EmbeddingService:
    """本地嵌入模型服务，自动选择 PyTorch / ONNX 后端"""

    def __init__(self, model_name: str = None, model_cache_dir: str = None):
        self.model_name = model_name or DEFAULT_MODEL_NAME
        self.model_cache_dir = model_cache_dir
        self._backend = None
        self._model = None

        if model_cache_dir:
            cache_path = Path(model_cache_dir)
            cache_path.mkdir(parents=True, exist_ok=True)
            os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(cache_path))
            os.environ.setdefault("HF_HOME", str(cache_path))

    def _load_model(self):
        if self._model is not None:
            return
        # 优先 PyTorch（速度更快），失败则 ONNX
        err = None
        try:
            from sentence_transformers import SentenceTransformer
            import torch
            if not hasattr(torch, "Tensor"):
                raise ImportError("torch not fully loaded")
            logger.info("加载嵌入模型(PyTorch): %s", self.model_name)
            self._model = SentenceTransformer(self.model_name)
            self._backend = "torch"
            logger.info("嵌入模型加载完成(PyTorch)，维度: %d", self._model.get_embedding_dimension())
            return
        except Exception as e:
            err = e
            logger.warning("PyTorch 后端加载失败，尝试 ONNX 后端: %s", e)

        try:
            logger.info("加载嵌入模型(ONNX): %s", self.model_name)
            self._model = _OnnxModel(self.model_name)
            self._backend = "onnx"
            logger.info("嵌入模型加载完成(ONNX)")
        except Exception as e:
            raise RuntimeError(
                f"嵌入模型加载失败（PyTorch 和 ONNX 均不可用）。\n"
                f"PyTorch 错误: {err}\nONNX 错误: {e}\n"
                f"请安装: pip install sentence-transformers 或 pip install onnxruntime tokenizers"
            )

    def encode(self, texts: Union[str, List[str]], normalize: bool = True) -> np.ndarray:
        self._load_model()
        if isinstance(texts, str):
            texts = [texts]
        return self._model.encode(texts, normalize_embeddings=normalize, show_progress_bar=False, batch_size=32)

    def encode_query(self, query: str) -> np.ndarray:
        self._load_model()
        query = f"{_BGE_QUERY_PREFIX}{query}"
        return self.encode(query, normalize=True)[0]

    def similarity(self, text_a: str, text_b: str) -> float:
        embeddings = self.encode([text_a, text_b])
        return float(np.dot(embeddings[0], embeddings[1]))

    def get_dimension(self) -> int:
        self._load_model()
        return self._model.get_embedding_dimension()

    def get_model(self):
        """返回底层模型对象（兼容 rag.py 调用 .encode()）"""
        self._load_model()
        return self._model


def get_embedding_service(model_name: str = None, model_cache_dir: str = None) -> EmbeddingService:
    global _instance
    if _instance is None:
        _instance = EmbeddingService(model_name=model_name, model_cache_dir=model_cache_dir)
    return _instance


def get_sentence_transformer(model_name: str = None, model_cache_dir: str = None):
    service = get_embedding_service(model_name=model_name, model_cache_dir=model_cache_dir)
    return service.get_model()
