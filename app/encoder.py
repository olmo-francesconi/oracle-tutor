import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer


class Encoder:
    """Sentence-transformers ONNX export (onnx/model.onnx + tokenizer.json), mean-pooled and L2-normalized.

    The build embeds the corpus with this exact class, so corpus and query vectors always come from one encoder.
    """

    def __init__(self, model_dir: Path, threads: int = 1):
        self.model_dir = model_dir
        cfg = model_dir / "sentence_bert_config.json"
        max_len = json.loads(cfg.read_text()).get("max_seq_length", 256) if cfg.exists() else 256
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=max_len)
        self.tokenizer.enable_padding(pad_id=self.tokenizer.token_to_id("[PAD]") or 0, pad_token="[PAD]")
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        # Arena off and BASIC optimization: ~100-200 MB less RSS for one short query at a time.
        opts.enable_cpu_mem_arena = False
        opts.enable_mem_pattern = False
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        self.session = ort.InferenceSession(str(model_dir / "onnx" / "model.onnx"), opts, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}

    def encode(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        out = []
        for start in range(0, len(texts), batch_size):
            enc = self.tokenizer.encode_batch(texts[start : start + batch_size])
            feed = {
                "input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64),
                "token_type_ids": np.array([e.type_ids for e in enc], dtype=np.int64),
            }
            tokens = np.asarray(self.session.run(None, {k: v for k, v in feed.items() if k in self.inputs})[0])
            mask = feed["attention_mask"][..., None].astype(np.float32)
            pooled = (tokens * mask).sum(1) / np.clip(mask.sum(1), 1e-9, None)
            out.append(pooled / np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None))
        return np.concatenate(out).astype(np.float32) if out else np.zeros((0, 0), np.float32)
