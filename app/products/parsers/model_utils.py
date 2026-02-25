import os, json, re, time
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from bs4 import BeautifulSoup
from transformers import AutoTokenizer, AutoModel

def mean_pool(last_hidden_state, attention_mask):
    mask = attention_mask.unsqueeze(-1).type_as(last_hidden_state)
    summed = (last_hidden_state * mask).sum(dim=1)
    counts = mask.sum(dim=1).clamp(min=1e-9)
    return summed / counts

class StudentDistillModel(nn.Module):
    def __init__(self, encoder, hidden_size, out_dim=6, dropout=0.1):
        super().__init__()
        self.encoder = encoder
        self.dropout = nn.Dropout(dropout)
        self.head = nn.Linear(hidden_size, out_dim)

    def forward(self, input_ids, attention_mask):
        out = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        pooled = mean_pool(out.last_hidden_state, attention_mask)
        pooled = F.normalize(pooled, p=2, dim=-1)
        pooled = self.dropout(pooled)
        scores = self.head(pooled)
        return scores

def load_runtime_config(model_dir: str):
    cfg_path = os.path.join(model_dir, "config_runtime.json")
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)
    
def apply_rules(text: str, AXES, RULES):
    t = str(text).lower()
    scores = np.zeros(len(AXES), dtype=np.float32)
    for j, ax in enumerate(AXES):
        for kw in RULES.get(ax, []):
            target = str(kw).lower()

            # 울 예외: "겨울" 포함된 문맥은 울 무시
            if target == "울":
                clean = t.replace("겨울", " ")
                if "울" in clean:
                    if ax == "quality_logic":
                        scores[j] = 1.0
                    break
                else:
                    continue

            if target in t:
                scores[j] = 1.0
                break
    return scores

class KeywordAxisInfer:
    def __init__(self, model_dir: str, device: str | None = None):
        self.model_dir = model_dir
        self.cfg = load_runtime_config(model_dir)

        self.AXES = self.cfg["AXES"]
        self.THRESHOLDS = self.cfg["THRESHOLDS"]
        self.RULES = self.cfg["RULES"]
        self.rule_weight = float(self.cfg.get("rule_weight", 1.2))
        self.max_len = int(self.cfg.get("max_len", 128))
        dropout = float(self.cfg.get("dropout", 0.0))

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        base_name = self.cfg.get("STUDENT_NAME", "intfloat/multilingual-e5-base")

        # ✅ tokenizer/encoder 둘 다 base_name에서 로드
        self.tokenizer = AutoTokenizer.from_pretrained(base_name)
        self.encoder = AutoModel.from_pretrained(base_name).to(self.device)

        hidden = self.encoder.config.hidden_size
        self.student = StudentDistillModel(
            self.encoder, hidden_size=hidden, out_dim=len(self.AXES), dropout=dropout
        ).to(self.device)

        head_path = os.path.join(model_dir, "student_head.pt")
        state = torch.load(head_path, map_location=self.device)

        # ✅ head만 로드 (저장 형태 2가지 모두 대응)
        # 1) {"weight":..., "bias":...}
        if "weight" in state and "bias" in state:
            self.student.head.load_state_dict(state, strict=True)
        # 2) {"head.weight":..., "head.bias":...} 혹은 전체 state_dict
        else:
            # head.* 만 추출해서 로드 시도
            head_state = {k.replace("head.", ""): v for k, v in state.items() if k.startswith("head.")}
            if head_state:
                self.student.head.load_state_dict(head_state, strict=True)
            else:
                # 마지막 수단: 전체 로드(학습 때 전체 저장했으면 여기서 성공)
                self.student.load_state_dict(state, strict=False)

        self.student.eval()

    @torch.no_grad()
    def predict_scores(self, texts, batch_size: int = 128):
        outs = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            enc = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_len,
                return_tensors="pt"
            )
            input_ids = enc["input_ids"].to(self.device)
            attn = enc["attention_mask"].to(self.device)

            s = self.student(input_ids, attn)  # (B,6)
            outs.append(s.detach().cpu().numpy())
        return np.vstack(outs).astype(np.float32)

    def infer(self, texts, batch_size: int = 128):
        student_scores = self.predict_scores(texts, batch_size=batch_size)
        rule_scores = np.vstack([apply_rules(t, self.AXES, self.RULES) for t in texts])

        final_scores = student_scores + self.rule_weight * rule_scores

        final_labels = np.zeros_like(final_scores, dtype=np.int32)
        for j, ax in enumerate(self.AXES):
            final_labels[:, j] = (final_scores[:, j] >= float(self.THRESHOLDS[ax])).astype(np.int32)

        return final_scores, final_labels
