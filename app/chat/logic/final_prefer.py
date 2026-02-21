# app/chat/logic/final_prefer.py
# -*- coding: utf-8 -*-
import os, json
import numpy as np
import pandas as pd
import joblib

# =========================
# Config
# =========================
FEATURE_COLS = [
    "discount_rate","review_score","review_count","product_likes",
    "platform","is_direct_shipping","free_shipping",
    "sim_quality_logic","sim_trend_hype","sim_temptation",
    "sim_fit_anxiety","sim_bundle","sim_confidence"
]
SIM_COLS = [c for c in FEATURE_COLS if c.startswith("sim_")]
LABEL_POS = "positive"
LABEL_NEG = "negative"
REVIEW_BEST_LOW   = 10
REVIEW_BEST_HIGH  = 500
REVIEW_FALL_END   = 4000
DISCOUNT_OK_MAX   = 45
DISCOUNT_FALL_END = 60
BINARY_COLS = ["free_shipping"] + SIM_COLS
COUNT_LOG_COLS = ["product_likes"]
PERSONAL_SCALE_COLS = ["discount_rate","review_score","review_count","product_likes","is_direct_shipping"]
N0_ALPHA = 20

# =========================
# Utils
# =========================
def _safe_float(v, default=0.0):
    try:
        if v is None: return default
        if isinstance(v, str): v = v.replace(",", "").replace("%", "").strip()
        return float(v)
    except: return default

def sigmoid(x):
    x = np.clip(x, -30, 30)
    return 1.0 / (1.0 + np.exp(-x))

def alpha_n(n, N0=N0_ALPHA):
    return float(N0 / (N0 + n))

def normalize_item_schema(item: dict) -> dict:
    x = {}
    for c in FEATURE_COLS: x[c] = _safe_float(item.get(c, 0), 0.0)
    for c in SIM_COLS: x[c] = 1.0 if _safe_float(x.get(c, 0.0), 0.0) >= 0.5 else 0.0
    x["free_shipping"] = 1.0 if _safe_float(x.get("free_shipping", 0.0), 0.0) >= 0.5 else 0.0
    x["is_direct_shipping"] = _safe_float(x.get("is_direct_shipping", 0.0), 0.0)
    return x

def format_actual_value(feat_name, actual_val):
    if feat_name == 'discount_rate': return f"{int(_safe_float(actual_val))}%"
    elif feat_name == 'review_count': return f"{int(_safe_float(actual_val))}개"
    elif feat_name == 'review_score': return f"{_safe_float(actual_val)}점"
    return ""

# =========================
# PRIOR
# =========================
def load_prior_artifacts(prior_dir: str):
    prior_clf   = joblib.load(os.path.join(prior_dir, "prior_clf.joblib"))
    scaler_cont = joblib.load(os.path.join(prior_dir, "scaler_cont.joblib"))
    meta        = joblib.load(os.path.join(prior_dir, "prior_meta.joblib"))
    ref_item    = joblib.load(os.path.join(prior_dir, "prior_ref.joblib"))
    return prior_clf, scaler_cont, meta, ref_item

def _logify_counts_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in ["review_count", "product_likes"]:
        if c in df.columns: df[c] = np.log1p(df[c].astype(float))
    return df

def _binarize_is_direct_shipping(v):
    return float(_safe_float(v, 0.0) >= 1.0)

def score_prior(item_json: dict, persona_type: str,
               prior_clf, scaler_cont, meta, ref_item, topk=2):
    FEATURE_COLS_ = meta["FEATURE_COLS"]
    SIM_COLS_     = meta["SIM_COLS"]
    ALL_COLS_TRAIN= meta["ALL_COLS_TRAIN"]
    PERSONA_COLS  = meta["PERSONA_COLS"]
    SCALE_COLS    = meta["SCALE_COLS"]
    PASS_COLS     = meta["PASS_COLS"]
    MIXED_COL_ORDER = meta["MIXED_COL_ORDER"]
    EXCLUDE_AT_INFERENCE = set(meta["EXCLUDE_AT_INFERENCE"])

    item = normalize_item_schema(item_json)
    df_item = pd.DataFrame([item])
    X_feat = _logify_counts_df(df_item[FEATURE_COLS_].copy()).iloc[0].astype(float)
    X_feat["is_direct_shipping"] = _binarize_is_direct_shipping(X_feat["is_direct_shipping"])
    for c in SIM_COLS_: X_feat[c] = float(_safe_float(X_feat[c], 0.0) >= 0.5)

    disc = float(X_feat["discount_rate"])
    item_high = float(disc >= 80)
    item_mid  = float((disc >= 30) and (disc < 80))
    delta = {c: float(X_feat[c]) - float(ref_item.get(c, 0.0)) for c in FEATURE_COLS_}
    delta["discount_high_flag"] = item_high - float(ref_item.get("discount_high_flag", 0.0))
    delta["discount_mid_flag"]  = item_mid  - float(ref_item.get("discount_mid_flag", 0.0))

    for c in EXCLUDE_AT_INFERENCE:
        if c in delta: delta[c] = 0.0

    X_row = pd.Series(0.0, index=ALL_COLS_TRAIN)
    for c in FEATURE_COLS_:
        if c in X_row.index: X_row[c] = float(delta[c])
    for c in ["discount_high_flag", "discount_mid_flag"]:
        if c in X_row.index: X_row[c] = float(delta[c])

    for pc in PERSONA_COLS: X_row[pc] = 0.0
    pcol = f"p_{persona_type}"
    if pcol not in PERSONA_COLS: raise ValueError(f"persona_type '{persona_type}' missing in meta.")
    X_row[pcol] = 1.0

    X_df = X_row.to_frame().T
    X_cont_z = scaler_cont.transform(X_df[SCALE_COLS].values)
    X_pass   = X_df[PASS_COLS].values.astype(float)
    Xz = np.concatenate([X_cont_z, X_pass], axis=1)

    p = float(prior_clf.predict_proba(Xz)[0, 1])
    prior_score_100 = int(round(p * 100))

    w = prior_clf.coef_.reshape(-1)
    contrib = (Xz.reshape(-1) * w)
    reason_features = [c for c in FEATURE_COLS_ if c not in EXCLUDE_AT_INFERENCE]
    feat_idx = [MIXED_COL_ORDER.index(c) for c in reason_features]
    contrib_feat = contrib[feat_idx]
    idx_local = np.argsort(contrib_feat)[::-1][:topk]

    top2_with_weights = []
    for i in idx_local:
        feat_name = reason_features[i]
        actual_val = item_json.get(feat_name, 0)
        desc = format_actual_value(feat_name, actual_val)
        weight = float(contrib_feat[i])
        top2_with_weights.append((feat_name, desc, weight))
    return prior_score_100, top2_with_weights

# =========================
# PERSONAL
# =========================
def _trapezoid_utility(x, best_low, best_high, fall_end):
    x = x.astype(float)
    u = np.zeros_like(x, dtype=float)
    up = (x > 0) & (x < best_low)
    u[up] = x[up] / max(best_low, 1e-9)
    u[(x >= best_low) & (x <= best_high)] = 1.0
    down = (x > best_high) & (x < fall_end)
    u[down] = (fall_end - x[down]) / max((fall_end - best_high), 1e-9)
    return np.clip(u, 0.0, 1.0)

def _discount_utility(d, ok_max, fall_end):
    d = d.astype(float)
    u = np.ones_like(d, dtype=float)
    down = (d > ok_max) & (d < fall_end)
    u[down] = (fall_end - d[down]) / max((fall_end - ok_max), 1e-9)
    u[d >= fall_end] = 0.0
    return np.clip(u, 0.0, 1.0)

def preprocess_df_for_personal(df_in: pd.DataFrame, scaler_mean: pd.Series, scaler_std: pd.Series):
    dfp = df_in[FEATURE_COLS].copy()
    dfp["platform"] = 0.0
    for c in COUNT_LOG_COLS: dfp[c] = np.log1p(dfp[c].astype(float))
    dfp["review_count"] = _trapezoid_utility(dfp["review_count"].astype(float), REVIEW_BEST_LOW, REVIEW_BEST_HIGH, REVIEW_FALL_END)
    dfp["discount_rate"] = _discount_utility(dfp["discount_rate"].astype(float), DISCOUNT_OK_MAX, DISCOUNT_FALL_END)
    for c in BINARY_COLS: dfp[c] = (dfp[c].astype(float) >= 0.5).astype(float)
    dfp["is_direct_shipping"] = dfp["is_direct_shipping"].astype(float)
    dfp = dfp.fillna(0.0).astype(float)
    dfp.loc[:, PERSONAL_SCALE_COLS] = (dfp[PERSONAL_SCALE_COLS] - scaler_mean) / scaler_std
    return dfp

def init_profile_from_global_stats(d: int, scaler_mean: pd.Series, scaler_std: pd.Series, T: float = 1.0):
    return {
        "mu_like": np.zeros(d, dtype=float), "mu_regret": np.zeros(d, dtype=float),
        "n_pos": 0, "n_neg": 0, "scaler_mean": scaler_mean, "scaler_std": scaler_std, "T": float(T)
    }

def profile_n_effective(profile) -> int:
    return int(profile.get("n_pos", 0) + profile.get("n_neg", 0))

def _online_mean_update(mu: np.ndarray, x: np.ndarray, n_before: int) -> np.ndarray:
    return (mu * n_before + x) / (n_before + 1)

def update_profile(profile: dict, item_json: dict, label: str):
    item = normalize_item_schema(item_json)
    df_item = pd.DataFrame([item])
    Xdf = preprocess_df_for_personal(df_item, profile["scaler_mean"], profile["scaler_std"])
    x = Xdf.iloc[0].values.astype(float)
    if str(label) == LABEL_POS:
        n = int(profile["n_pos"])
        profile["mu_like"] = _online_mean_update(profile["mu_like"], x, n)
        profile["n_pos"] = n + 1
    elif str(label) == LABEL_NEG:
        n = int(profile["n_neg"])
        profile["mu_regret"] = _online_mean_update(profile["mu_regret"], x, n)
        profile["n_neg"] = n + 1
    return profile

def personal_raw_and_contrib(x_vec: np.ndarray, mu_like: np.ndarray, mu_regret: np.ndarray, T: float):
    like_gap = np.abs(x_vec - mu_like); reg_gap = np.abs(x_vec - mu_regret)
    contrib = reg_gap - like_gap; raw = float(contrib.sum() / max(T, 1e-9))
    return raw, contrib

def score_personal(item_json: dict, profile: dict, topk=2):
    item = normalize_item_schema(item_json)
    df_item = pd.DataFrame([item])
    Xdf = preprocess_df_for_personal(df_item, profile["scaler_mean"], profile["scaler_std"])
    x_vec = Xdf.iloc[0].values.astype(float)
    raw, contrib = personal_raw_and_contrib(x_vec, profile["mu_like"], profile["mu_regret"], profile["T"])
    score100 = int(round(float(sigmoid(raw)) * 100))
    valid_idx = [i for i, f in enumerate(FEATURE_COLS) if f != "platform"]
    idx_pos = sorted(valid_idx, key=lambda i: contrib[i], reverse=True)[:topk]
    idx_rsk = sorted(valid_idx, key=lambda i: contrib[i])[:topk]

    def get_drivers_with_weights(indices):
        drivers = []
        for i in indices:
            f_name = FEATURE_COLS[i]
            val = item_json.get(f_name, 0)
            weight = float(contrib[i])
            drivers.append((f_name, format_actual_value(f_name, val), weight))
        return drivers

    if score100 <= 60: return score100, "risk", get_drivers_with_weights(idx_rsk)
    return score100, "positive", get_drivers_with_weights(idx_pos)

# =========================
# TOTAL inference
# =========================
def infer_all(item_json: dict, persona_type: str, prior_dir: str, profile: dict = None):
    from ..constants import DEFAULT_VALUES
    prior_clf, scaler_cont, meta, ref_item = load_prior_artifacts(prior_dir)
    prior_score, prior_top2 = score_prior(item_json, persona_type, prior_clf, scaler_cont, meta, ref_item, topk=2)

    if profile is None or profile_n_effective(profile) == 0:
        personal_score, personal_reason_type, personal_top2, n_eff, a = DEFAULT_VALUES["preference_neutral_score"], "neutral", [], 0, 1.0
    else:
        personal_score, personal_reason_type, personal_top2 = score_personal(item_json, profile, topk=2)
        n_eff = profile_n_effective(profile); a = alpha_n(n_eff, N0_ALPHA)

    total = int(round(a * prior_score + (1.0 - a) * personal_score))
    return {
        "prior_score": prior_score, 
        "prior_reason_top2": prior_top2, 
        "personal_score": personal_score, 
        "personal_reason_type": personal_reason_type,
        "personal_reason_top2": personal_top2, 
        "alpha": float(a),
        "n_effective": int(n_eff), 
        "total_score": total
    }