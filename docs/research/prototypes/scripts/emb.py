"""Minimal ONNX sentence embedder (all-MiniLM-L6-v2, mean pooling, L2 norm) for offline experiments."""
import os
import time

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

MODEL_DIR = os.environ.get("EMB_DIR", "models/minilm/onnx")


class Embedder:
    def __init__(self, max_len: int = 128, threads: int = 4):
        self.tok = Tokenizer.from_file(os.path.join(MODEL_DIR, "tokenizer.json"))
        self.tok.enable_truncation(max_length=max_len)
        self.tok.enable_padding(pad_id=0, pad_token="[PAD]")
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        self.sess = ort.InferenceSession(os.path.join(MODEL_DIR, "model.onnx"), so, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.sess.get_inputs()}

    def encode(self, texts: list[str], batch: int = 32) -> np.ndarray:
        out = []
        for k in range(0, len(texts), batch):
            enc = self.tok.encode_batch(texts[k : k + batch])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            h = self.sess.run(None, feed)[0]
            m = mask[..., None].astype(np.float32)
            v = (h * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
            v /= np.linalg.norm(v, axis=1, keepdims=True)
            out.append(v)
        return np.vstack(out)


def timed(fn, *a, **k):
    t = time.perf_counter()
    r = fn(*a, **k)
    return r, time.perf_counter() - t
