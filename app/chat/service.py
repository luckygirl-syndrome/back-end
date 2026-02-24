"""
app/chat/service.py

비즈니스 로직 담당.
- parse_and_save_product: 상품 파싱 + DB/Redis 저장 (Background Task, 동기)
- init_chat_session: finalize-survey에서 호출. JSON 조립 → Redis 세션 저장 → 첫 응답 생성
- handle_message: /{chat_id}/messages/ 에서 호출. 세션 로드 → 프롬프트 조립 → 응답 생성
"""
import os
import datetime
import json
import re
import traceback

import joblib
from sqlalchemy.orm import Session

from app.users.models import User
from app.products.models import Product, UserProduct
from app.products.parsers.item_parser import extract_features_from_url
from app.chat.logic.impulse_calculator import analyze_product_risk
from app.chat.logic.final_prefer import infer_all
from app.chat.logic.user_survey import determine_mode
from .constants import (
    IMPULSE_GUIDE_DATA, SURVEY_TEXT_MAPPING, DEFAULT_VALUES,
    SURVEY_SCORE_TABLE, PRIOR_TEXT, PERSONAL_POS_TEXT, PERSONAL_RISK_TEXT,
)
from . import repository
from . import agent

import redis

from app.core.config import settings

# ──────────────────────────────────────────────
# 동기 Redis 클라이언트 (Background Task에서 사용)
# ──────────────────────────────────────────────
redis_client = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=0,
    decode_responses=True,
)

# ML 모델 디렉토리
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRIOR_MODEL_DIR = os.path.join(BASE_DIR, "models", "artifacts_prior")
print(f"🚀 DEBUG: PRIOR_MODEL_DIR is -> {PRIOR_MODEL_DIR}")

# 챗봇 설명용 한글 매핑
FEATURE_KO = {
    'discount_rate': '할인율', 'review_count': '리뷰 수', 'review_score': '평점',
    'product_like': '찜 수', 'shipping_info': '배송 정보', 'free_shipping': '무료 배송',
    'sim_trend_hype': '유행/대란 키워드', 'sim_temptation': '자극적 홍보 문구',
    'sim_fit_anxiety': '핏/체형 보정 문구', 'sim_quality_logic': '소재/퀄리티 강조',
    'sim_bundle': '1+1/묶음 할인', 'sim_confidence': 'MD추천/보증'
}


# ──────────────────────────────────────────────
# 1. 상품 파싱 + 저장 (Background Task — 동기)
# ──────────────────────────────────────────────
def clean_persona_code(user):
    """프로젝트 표준 순서(1:D/N, 2:S/A, 3:M/T)에 맞춰 페르소나 코드 정렬"""
    raw = getattr(user, 'persona_type', "DSM")
    if isinstance(raw, dict):
        raw = raw.get('persona_type', 'DSM')
    elif isinstance(raw, str) and raw.startswith('{'):
        try:
            data = json.loads(raw)
            raw = data['persona'].get('persona_type', 'DSM') if isinstance(data.get('persona'), dict) else data.get('persona_type', 'DSM')
        except:
            raw = "DSM"

    code = str(raw).replace("-", "").replace(" ", "").upper()
    axis1 = {'D', 'N'}
    axis2 = {'S', 'A'}
    axis3 = {'M', 'T'}
    res = ["", "", ""]

    for char in code:
        if char in axis1: res[0] = char
        elif char in axis2: res[1] = char
        elif char in axis3: res[2] = char

    if all(res):
        return "".join(res)
    return code


def parse_and_save_product(db: Session, url: str, user: User):
    """Background Task: URL 파싱 → 분석 → DB 저장 → Redis 캐시."""
    try:
        user_persona_code = clean_persona_code(user)
        model_ready_code = f"{user_persona_code[0]}-{user_persona_code[1]}-{user_persona_code[2]}"

        result = extract_features_from_url(url)
        if not result or result.get("product_name") == "Error":
            return None

        # 분석
        risk_res = analyze_product_risk(result, model_ready_code)
        pref_out = infer_all(item_json=result, persona_type=model_ready_code, prior_dir=PRIOR_MODEL_DIR)
        impulse_score = int(risk_res.get('total_score', 0))
        total_pref_score = int(pref_out['total_score'])

        # DB 저장
        product = db.query(Product).filter(Product.product_name == result['product_name']).first()
        if not product:
            product = Product(
                product_img=result.get('product_img', ''),
                product_name=result.get('product_name', 'Unknown'),
                platform=result.get('platform', 'Unknown'),
                category=result.get('category', '기타'),
                free_shipping=bool(result.get('free_shipping', 0)),
                price=int(result.get('discounted_price', 0)),
                discount_rate=float(result.get('discount_rate', 0)),
                is_direct_shipping=bool(result.get('is_direct_shipping', 0)),
                review_count=int(result.get('review_count', 0)),
                review_score=float(result.get('review_score', 0.0)),
                product_likes=str(result.get('product_likes', '0')),
                **{col: result.get(col, 0) for col in [
                    "sim_temptation", "sim_trend_hype", "sim_fit_anxiety",
                    "sim_quality_logic", "sim_bundle", "sim_confidence"
                ]}
            )
            db.add(product)
            db.flush()

        user_prod = UserProduct(
            user_id=user.user_id, product_id=product.product_id,
            user_type=user_persona_code, risk_score_1=impulse_score,
            status="IN_PROGRESS", preference_score=total_pref_score
        )
        db.add(user_prod)
        db.commit()

        # 실제 수치 데이터
        feature_values = {
            "discount_rate": result.get('discount_rate', 0),
            "review_score": result.get('review_score', 0),
            "review_count": result.get('review_count', 0),
            "product_likes": result.get('product_likes', 0),
            "price": result.get('discounted_price', 0),
            "free_shipping": result.get('free_shipping', 0)
        }

        # 캐시용 데이터 조립
        details = {
            "top_2_causes": risk_res.get('top_2_causes', []),
            "prior_reasons": pref_out.get('prior_reason_top2', []),
            "personal_reasons": pref_out.get('personal_reason_top2', []),
            "prior_score": pref_out.get('prior_score', 0),
            "personal_score": pref_out.get('personal_score', 0),
            "personal_reason_type": pref_out.get('personal_reason_type', 'neutral'),
            "feature_values": feature_values
        }

        # ✅ Redis 저장 (신규 키 네이밍: chat:{user_product_id}:item_json)
        chat_id = user_prod.user_product_id
        cache_key = f"chat:{chat_id}:item_json"
        redis_client.setex(cache_key, 86400, json.dumps(details, ensure_ascii=False))
        print(f"✅ [service] 상품 분석 캐시 저장: {cache_key}")

        # 터미널 리포트
        prompt_data = {
            "user_context": {"persona_type": user_persona_code, "target_style": getattr(user, 'chu_gu_me', '심플'), "n_effective": pref_out["n_effective"]},
            "analysis_result": {"total_prefer_score": total_pref_score, "impulse_score": impulse_score, "alpha_value": pref_out["alpha"]},
            "prior_analysis": {"score": pref_out["prior_score"], "top_reasons": [{"feature": r[0], "value": feature_values.get(r[0])} for r in pref_out["prior_reason_top2"]]},
            "personal_analysis": {"score": pref_out["personal_score"], "reason_type": pref_out["personal_reason_type"], "top_reasons": [{"feature": r[0], "value": feature_values.get(r[0])} for r in pref_out["personal_reason_top2"]]},
            "impulse_block": {"score": impulse_score, "label": risk_res["risk_label"], "level": risk_res["risk_level"], "top_causes": [{"name": c["feature_name"], "value": feature_values.get(c["feature_key"]), "detail": c["detail"]} for c in risk_res["top_2_causes"]]}
        }
        print_analysis_report(user.user_id, user_persona_code, product.product_name, pref_out, risk_res, prompt_data)

        return prompt_data

    except Exception as e:
        db.rollback()
        print(f"❌ 에러 발생:\n{traceback.format_exc()}")
        return None


def print_analysis_report(user_id, persona, p_name, pref, risk, prompt_data):
    """터미널에 분석 결과와 프롬프트 주입 데이터를 통째로 출력"""
    print("\n" + "=" * 80)
    print(f" 🚀 [SYSTEM REPORT] USER: {user_id} | PERSONA: {persona}")
    print(f" 📦 PRODUCT: {p_name}")
    print("=" * 80)
    print(f" [SUMMARY]")
    print(f" - Risk Score  : {risk['total_score']}점 ({risk['risk_label']})")
    print(f" - Pref. Score : {pref['total_score']}점 (Alpha: {pref['alpha']:.2f})")
    print("-" * 80)
    print(f" 📝 [PROMPT INJECTION DATA]")
    print(json.dumps(prompt_data, indent=4, ensure_ascii=False))
    print("-" * 80)
    print(f" ✅ 분석 및 프롬프트 준비 완료 (Timestamp: {datetime.datetime.now().strftime('%H:%M:%S')})")
    print("=" * 80 + "\n")


# ──────────────────────────────────────────────
# 2. 세션 초기화 (finalize-survey에서 호출)
# ──────────────────────────────────────────────
async def init_chat_session(
    db: Session,
    user_id: int,
    product_id: int,
    chat_id: int,
    user_answers: dict,
) -> str:
    """
    설문 완료 후 호출. 
    1) 분석 데이터 + 설문 결과로 완전체 JSON 조립
    2) Redis에 ctx_fixed 저장
    3) 첫 Gemini 호출 → 첫 응답 반환
    """
    # DB 조회
    record = db.query(UserProduct).filter(
        UserProduct.user_product_id == chat_id
    ).first()
    product = db.query(Product).filter(Product.product_id == product_id).first()
    user = db.query(User).filter(User.user_id == user_id).first()

    if not record or not product or not user:
        return "데이터를 불러오는 데 실패했어. 다시 시도해줄래? 🧐"

    # ── Redis에서 분석 상세 데이터 가져오기 ──
    cache_key = f"chat:{chat_id}:item_json"
    cached_raw = redis_client.get(cache_key)

    if not cached_raw:
        print(f"⚠️ 캐시 만료됨: {cache_key}")
        details = {
            "top_2_causes": [],
            "prior_reasons": [],
            "personal_reasons": [],
            "prior_score": 0,
            "personal_score": 0,
            "feature_values": {}
        }
    else:
        details = json.loads(cached_raw)

    # ── 모드 결정 + 가이드 데이터 ──
    mode = determine_mode([
        {"q_id": 1, "answer_id": user_answers.get('q1')},
        {"q_id": 2, "answer_id": user_answers.get('q2')},
        {"q_id": 3, "answer_id": user_answers.get('q3')}
    ])

    b_score = (
        SURVEY_SCORE_TABLE["q1"].get(user_answers.get('q1'), (0, 0))[0]
        + SURVEY_SCORE_TABLE["q2"].get(user_answers.get('q2'), (0, 0))[0]
        + SURVEY_SCORE_TABLE["q3"].get(user_answers.get('q3'), (0, 0))[0]
    )
    level_num = min(5, max(1, b_score))
    level_key = f"Level {level_num}"
    guide_info = IMPULSE_GUIDE_DATA.get(level_key)

    persona_suffix = record.user_type[-1].lower()
    persona_prefix = "default_" if persona_suffix == 't' else "myway_"

    p_type = details.get('personal_reason_type', 'positive')
    personal_text_dict = PERSONAL_RISK_TEXT if p_type == 'risk' else PERSONAL_POS_TEXT

    # ── 완전체 JSON 조립 ──
    final_input_json = {
        "meta": {
            "trace_id": str(re.sub(r'[^a-zA-Z0-9]', '', str(datetime.datetime.now().timestamp()))),
            "timestamp": datetime.datetime.now().isoformat()
        },
        "user_context": {
            "persona_type": record.user_type,
            "frequent_malls": json.loads(user.favorite_shops) if user.favorite_shops and user.favorite_shops.startswith("[") else ([user.favorite_shops] if user.favorite_shops else []),
            "target_style": getattr(user, 'chu_gu_me', '심플')
        },
        "product_context": {
            "name": product.product_name,
            "brand": product.brand if hasattr(product, 'brand') else product.platform,
            "mall": product.platform,
            "price": product.price,
            "category": product.category
        },
        "mode_block": {"current_mode": mode},
        "impulse_block": {
            "impulse_score": record.risk_score_1,
            "impulse_reason_top2": [
                {
                    "feature_key": cause["feature_key"],
                    "value": details.get('feature_values', {}).get(cause["feature_key"]),
                    "weight": round(cause["score_contribution"] / max(1, record.risk_score_1), 2),
                    "guide": guide_info["features"].get(
                        f"review_count_{persona_suffix}" if cause["feature_key"] == "review_count" else cause["feature_key"],
                        "이 부분 주의깊게 봐!"
                    )
                } for cause in details.get('top_2_causes', [])
            ]
        },
        "preference_block": {
            "total_score": record.preference_score,
            "mixing": {"preference_priority": DEFAULT_VALUES["preference_priority"]},
            "prior_score": details.get('prior_score', 0),
            "prior_reason_top2": [
                {
                    "feature_key": r[0],
                    "value": details.get('feature_values', {}).get(r[0]),
                    "guide": PRIOR_TEXT.get(
                        f"{persona_prefix}review_count" if r[0] == "review_count" else r[0],
                        f"너랑 비슷한 유형은 '{FEATURE_KO.get(r[0], r[0])}' 조건이 만족스러우면 고민이 줄어드는 편이야."
                    )
                } for r in details.get('prior_reasons', [])
            ],
            "personal_score": details.get('personal_score', 0),
            "personal_reason_top2": [
                {
                    "feature_key": r[0],
                    "value": details.get('feature_values', {}).get(r[0]),
                    "guide": personal_text_dict.get(
                        f"{persona_prefix}{r[0]}" if r[0] in ["review_count", "product_likes"] else r[0],
                        f"이 옷의 '{FEATURE_KO.get(r[0], r[0])}' 조건은 네 평소 스타일이랑 조금 다를 수 있어."
                    )
                } for r in details.get('personal_reasons', [])
            ]
        },
        "conversation_block": {
            "cart_duration": SURVEY_TEXT_MAPPING["q1"].get(user_answers.get('q1'), "방금 전"),
            "contact_reason": SURVEY_TEXT_MAPPING["q2"].get(user_answers.get('q2'), "궁금해서"),
            "purchase_certainty": SURVEY_TEXT_MAPPING["q3"].get(user_answers.get('q3'), "확신 없음"),
            "key_appeal": SURVEY_TEXT_MAPPING["qc"].get(user_answers.get('qc'), "디자인")
        },
        "strategy_matrix": {
            "level": level_num,
            "label": guide_info["label"],
            "goal": guide_info["goal"],
            "strategy": guide_info["strategy"]
        }
    }

    # ── Redis에 ctx_fixed 저장 (비동기) ──
    await repository.save_ctx_fixed(chat_id, final_input_json)
    print(f"✅ [service] ctx_fixed 저장 완료: chat:{chat_id}:ctx_fixed")

    # ── DB에도 백업 ──
    record.prompt_data = json.dumps(final_input_json, ensure_ascii=False)
    db.commit()

    # ── 로그 ──
    print("\n" + "=" * 50)
    print(f"🚀 LLM INPUT JSON (Trace: {final_input_json['meta']['trace_id']})")
    print("-" * 50)
    print(json.dumps(final_input_json, indent=4, ensure_ascii=False))
    print("=" * 50 + "\n")

    # ── 첫 Gemini 호출 ──
    first_input = "설문 완료!"
    clean_text, next_step, is_held, decision_code = await agent.generate_response(
        json_data=final_input_json,
        current_step=1,
        current_turn=1,
        user_input=first_input,
        history=[],
    )

    # ── 히스토리에 첫 턴 저장 ──
    await repository.push_history(chat_id, "user", first_input)
    await repository.push_history(chat_id, "assistant", clean_text)

    if decision_code:
        print(f"🎯 [DECISION CODE]: {decision_code}")

    return clean_text


# ──────────────────────────────────────────────
# 3. 채팅 메시지 처리 (/{chat_id}/messages/)
# ──────────────────────────────────────────────
async def handle_message(
    db: Session,
    chat_id: int,
    user_input: str,
) -> dict:
    """
    유저 메시지 수신 → 세션 로드 → 프롬프트 조립 → Gemini 호출 → 히스토리 저장.
    Returns: {"message": str, "is_exit": bool, "decision_code": str|None}
    """
    # ── 세션 데이터 로드 (MGET) ──
    _, ctx_fixed = await repository.get_session_data(chat_id)

    if not ctx_fixed:
        # Redis 만료 시 DB에서 복구
        record = db.query(UserProduct).filter(
            UserProduct.user_product_id == chat_id
        ).first()
        if record and record.prompt_data:
            ctx_fixed = json.loads(record.prompt_data)
            await repository.save_ctx_fixed(chat_id, ctx_fixed)
            print(f"🔄 [service] DB에서 ctx_fixed 복구: chat:{chat_id}")
        else:
            return {
                "message": "세션 데이터를 찾을 수 없어. 처음부터 다시 시작해줄래? 🧐",
                "is_exit": False,
                "decision_code": None,
            }

    # ── 히스토리 로드 ──
    history = await repository.get_history(chat_id)

    # ── 현재 step/turn 계산 ──
    user_msgs = [m for m in history if m.get("role") == "user"]
    current_turn = len(user_msgs) + 1  # 이번 턴은 +1

    # step은 기본 1로 시작. 히스토리에 [STEP_MOVED:2] 같은 이벤트가 있다면 별도 트래킹 필요
    # MVP에서는 ctx_fixed에 저장하거나, 마지막 assistant 메시지 분석으로 판별
    current_step = 1  # 기본값

    # ── Gemini 호출 ──
    clean_text, next_step, is_held, decision_code = await agent.generate_response(
        json_data=ctx_fixed,
        current_step=current_step,
        current_turn=current_turn,
        user_input=user_input,
        history=history,
    )

    # ── 히스토리 저장 (비동기) ──
    await repository.push_history(chat_id, "user", user_input)
    await repository.push_history(chat_id, "assistant", clean_text)

    is_exit = (next_step == "EXIT") or (next_step == 2)
    if decision_code:
        print(f"🎯 [DECISION CODE]: {decision_code}")
    if is_exit:
        print(f"🏁 [service] 대화 종료 감지 (chat_id={chat_id})")

    return {
        "message": clean_text,
        "is_exit": is_exit,
        "decision_code": decision_code,
    }


# ──────────────────────────────────────────────
# 설문 텍스트 변환 헬퍼 (기존 유지)
# ──────────────────────────────────────────────
def get_q1_text(val: int):
    mapping = {1: "방금 담았어 / 1시간 이내", 2: "1~2일 이내", 3: "일주일 이내", 4: "일주일 이상", 5: "한달 이상"}
    return mapping.get(val, "방금 전")


def get_q2_text(val: int):
    mapping = {1: "사도 되는지 확인받고 싶어서", 2: "그냥 이 옷 어떤가 궁금해서", 3: "오래 고민했는데 결정이 안 나서", 4: "사고나서 후회할까봐 걱정돼서"}
    return mapping.get(val, "궁금해서")


def get_q3_text(val: int):
    mapping = {1: "사고싶긴 한데 비슷한 옷들이 많아서 고민이 돼", 2: "장바구니 옷 중에 이게 제일 마음에 들어", 3: "이미 코디까지 다 생각해 둬서 사면 잘 입을 것 같아", 4: "다 좋은데.. 혹시 더 나은 게 있을까봐 불안해"}
    return mapping.get(val, "확신 없음")


def get_qc_text(val: int):
    mapping = {1: "가성비", 2: "시즌오프 세일 / 품절 임박", 3: "요즘 유행템 / 연예인 착용", 4: "소재 및 퀄리티", 5: "MD/인플루언서 픽", 6: "모델의 착용 핏", 7: "빠른 배송 필요"}
    return mapping.get(val, "디자인")