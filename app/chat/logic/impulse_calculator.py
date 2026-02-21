# app/chat/logic/impulse_calculator.py
import numpy as np

# 가중치 및 설정값들
WEIGHT_MATRIX = {
    'discount_rate':     {'D': 1.2, 'N': 1.1, 'S': 1.0, 'A': 1.0, 'T': 1.0, 'M': 1.0},
    'review_count':      {'D': 1.0, 'N': 1.2, 'S': 1.2, 'A': 0.9, 'T': 1.5, 'M': 0.6},
    'review_score':      {'D': 1.0, 'N': 1.2, 'S': 1.2, 'A': 1.0, 'T': 1.3, 'M': 1.0},
    'product_like':      {'D': 1.0, 'N': 1.0, 'S': 1.1, 'A': 1.0, 'T': 1.1, 'M': 0.8},
    'shipping_info':     {'D': 1.0, 'N': 1.1, 'S': 1.0, 'A': 1.0, 'T': 1.0, 'M': 1.0},
    'free_shipping':     {'D': 1.0, 'N': 1.1, 'S': 1.0, 'A': 1.0, 'T': 1.0, 'M': 1.0},
    'sim_trend_hype':    {'D': 1.0, 'N': 1.0, 'S': 1.5, 'A': 1.0, 'T': 1.5, 'M': 0.8},
    'sim_temptation':    {'D': 1.0, 'N': 1.0, 'S': 1.2, 'A': 1.0, 'T': 1.0, 'M': 1.0},
    'sim_fit_anxiety':   {'D': 1.0, 'N': 1.0, 'S': 1.0, 'A': 1.0, 'T': 1.0, 'M': 1.0},
    'sim_quality_logic': {'D': 1.0, 'N': 1.2, 'S': 1.0, 'A': 1.0, 'T': 1.0, 'M': 1.0},
    'sim_bundle':        {'D': 1.0, 'N': 1.0, 'S': 1.0, 'A': 1.0, 'T': 1.0, 'M': 1.0},
    'sim_confidence':    {'D': 1.0, 'N': 1.2, 'S': 1.2, 'A': 1.0, 'T': 1.2, 'M': 1.0},
}

RISK_LEVELS = [
    (0,  35,  "안심 (Safe)", 1),
    (36, 50,  "보통 (Normal)", 2),
    (51, 65,  "주의 (Caution)", 3),
    (66, 85,  "경고 (Warning)", 4),
    (86, 100, "위험 (Danger)", 5),
]

FEATURE_KO = {
    'discount_rate': '할인율', 'review_count': '리뷰 수', 'review_score': '평점',
    'product_like': '찜 수', 'shipping_info': '배송 정보', 'free_shipping': '무료 배송',
    'sim_trend_hype': '유행/대란 키워드', 'sim_temptation': '자극적 홍보 문구',
    'sim_fit_anxiety': '핏/체형 보정 문구', 'sim_quality_logic': '소재/퀄리티 강조',
    'sim_bundle': '1+1/묶음 할인', 'sim_confidence': 'MD추천/보증'
}

def soft_step(x, threshold, scale, max_val):
    return max_val / (1 + np.exp(-scale * (x - threshold)))

def gaussian_peak(x, peak, width, max_val):
    return max_val * np.exp(-((x - peak)**2) / (2 * width**2))

def parse_persona(persona_code):
    traits = {'D':0, 'N':0, 'S':0, 'A':0, 'T':0, 'M':0}
    if not persona_code: return traits
    clean_code = str(persona_code).replace('-', '')
    for char in clean_code:
        upper_char = char.upper()
        if upper_char in traits: traits[upper_char] = 1
    return traits

def analyze_product_risk(product_json: dict, persona_code: str):
    user_traits = parse_persona(persona_code)
    raw_scores = {}
    dr = product_json.get('discount_rate', 0)
    raw_scores['discount_rate'] = gaussian_peak(dr, 40, 15, 15)
    raw_scores['review_score'] = soft_step(product_json.get('review_score', 0), 4.3, 10, 8)
    raw_scores['product_like'] = soft_step(product_json.get('product_likes', 0), 1800, 0.002, 4)
    
    rc_raw = product_json.get('review_count', 0)
    base_rc_score = soft_step(rc_raw, 1000, 0.003, 6)
    if user_traits.get('M', 0) == 1:
        raw_scores['review_count'] = 0 if rc_raw <= 5 else 6 - base_rc_score
    else:
        raw_scores['review_count'] = base_rc_score

    raw_scores['shipping_info'] = 7 if product_json.get('is_direct_shipping', 0) else 0
    raw_scores['free_shipping'] = 7 if product_json.get('free_shipping', 0) else 0
    
    for col in ['sim_temptation', 'sim_fit_anxiety', 'sim_trend_hype', 'sim_quality_logic', 'sim_bundle', 'sim_confidence']:
        raw_scores[col] = 6 if product_json.get(col, 0) else 0

    weighted_breakdown = {}; stimulus_total = 0
    for feat, score in raw_scores.items():
        if score <= 0.01: continue
        weights = [WEIGHT_MATRIX[feat][t] for t, lvl in user_traits.items() if lvl > 0 and t in WEIGHT_MATRIX[feat]]
        w_final = sum(weights) / len(weights) if weights else 1.0
        weighted_val = score * w_final
        stimulus_total += weighted_val
        weighted_breakdown[feat] = weighted_val

    amp_D = 1.2 if user_traits.get('D', 0) == 1 else 1.0
    amp_N = 0.9 if user_traits.get('N', 0) == 1 else 1.0
    raw_total_score = 25 + (stimulus_total * amp_D * amp_N)
    
    if raw_total_score > 90:
        final_score = 90 + (10 * ((raw_total_score - 90) / (raw_total_score - 90 + 5)))
    else:
        final_score = raw_total_score
        
    final_score = max(0, min(final_score, 100))
    risk_stage_info = next((lvl for lvl in RISK_LEVELS if lvl[0] <= final_score <= lvl[1]), RISK_LEVELS[-1])
    sorted_factors = sorted(weighted_breakdown.items(), key=lambda x: x[1], reverse=True)[:2]
    top_causes = []
    for feat, val in sorted_factors:
        desc = ""
        if feat == 'discount_rate': desc = f"{dr}%"
        elif feat == 'review_count': desc = f"{rc_raw}개"
        elif feat == 'review_score': desc = f"{product_json.get('review_score',0)}점"
        top_causes.append({"feature_key": feat, "feature_name": FEATURE_KO.get(feat, feat), "score_contribution": round(val, 2), "detail": desc})

    return {
        "total_score": round(final_score, 1), "risk_label": risk_stage_info[2],
        "risk_level": risk_stage_info[3], "top_2_causes": top_causes, "breakdown": weighted_breakdown
    }