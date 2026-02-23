import os
import datetime
import json
import re
import traceback
import joblib
import google.generativeai as genai
from sqlalchemy.orm import Session

from app.users.models import User
from app.products.models import Product, UserProduct
from app.products.parsers.item_parser import extract_features_from_url
from app.chat.logic.impulse_calculator import analyze_product_risk
from app.chat.logic.final_prefer import infer_all
from app.chat.logic.user_survey import determine_mode
from .prompt import TobabaPromptBuilder
from .constants import IMPULSE_GUIDE_DATA, SURVEY_TEXT_MAPPING, DEFAULT_VALUES, SURVEY_SCORE_TABLE, PRIOR_TEXT, PERSONAL_POS_TEXT, PERSONAL_RISK_TEXT

import redis
import json

# Redis 연결 (설정에 따라 주소 변경)
redis_client = redis.Redis(
    host='localhost', 
    port=6379, 
    db=0, 
    decode_responses=True  # 이걸 해야 문자열로 바로 읽어와!
)

# 1. 현재 파일(service.py) 위치: app/chat/service.py
# 2. abspath(__file__) -> /home/ubuntu/Back-end/app/chat/service.py
# 3. 3번 올라가야 /home/ubuntu/Back-end/ (루트)가 나옴
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 4. 이제 모델 폴더 위치를 지정
# 만약 모델 폴더가 Back-end/models/artifacts_prior 라면:
PRIOR_MODEL_DIR = os.path.join(BASE_DIR, "models", "artifacts_prior")

# 5. (선택) 제대로 잡혔는지 터미널에 찍어보기 (서버 로그 확인용)
print(f"🚀 DEBUG: PRIOR_MODEL_DIR is -> {PRIOR_MODEL_DIR}")

# 챗봇 설명용 한글 매핑
FEATURE_KO = {
    'discount_rate': '할인율', 'review_count': '리뷰 수', 'review_score': '평점',
    'product_like': '찜 수', 'shipping_info': '배송 정보', 'free_shipping': '무료 배송',
    'sim_trend_hype': '유행/대란 키워드', 'sim_temptation': '자극적 홍보 문구',
    'sim_fit_anxiety': '핏/체형 보정 문구', 'sim_quality_logic': '소재/퀄리티 강조',
    'sim_bundle': '1+1/묶음 할인', 'sim_confidence': 'MD추천/보증'
}



def clean_persona_code(user):
    """프로젝트 표준 순서(1:D/N, 2:S/A, 3:M/T)에 맞춰 페르소나 코드 정렬"""
    # 1. 데이터 가져오기 (JSON/Dict 대응)
    raw = getattr(user, 'persona_type', "DSM")
    if isinstance(raw, dict):
        raw = raw.get('persona_type', 'DSM')
    elif isinstance(raw, str) and raw.startswith('{'):
        try:
            data = json.loads(raw)
            raw = data['persona'].get('persona_type', 'DSM') if isinstance(data.get('persona'), dict) else data.get('persona_type', 'DSM')
        except:
            raw = "DSM"

    # 2. 불순물 제거 및 대문자화
    code = str(raw).replace("-", "").replace(" ", "").upper()
    
    # 🚩 3. [핵심] 정해진 축 순서에 따라 재배치
    # 각 축에 해당하는 글자들을 정의
    axis1 = {'D', 'N'}
    axis2 = {'S', 'A'}
    axis3 = {'M', 'T'}
    
    res = ["", "", ""] # [축1, 축2, 축3] 자리를 만듦
    
    for char in code:
        if char in axis1: res[0] = char
        elif char in axis2: res[1] = char
        elif char in axis3: res[2] = char
    
    # 만약 세 축의 글자가 다 모였다면 합쳐서 반환 (예: SDM -> DSM)
    if all(res):
        return "".join(res)
    
    # 혹시라도 글자가 부족하면 그냥 원본 대문자 반환 (에러 방지)
    return code

def parse_and_save_product(db: Session, url: str, user: User):
    try:
        # 1. 일단 우리끼리 쓸 '순서 정렬된' 깔끔한 코드 생성 (예: DSM)
        user_persona_code = clean_persona_code(user) # 위에서 만든 정렬 로직 사용 (하이픈 제거 버전)

        # 2. 🔥 모델한테 줄 때만 하이픈 살짝 끼워넣기
        # DSM -> D-S-M
        model_ready_code = f"{user_persona_code[0]}-{user_persona_code[1]}-{user_persona_code[2]}"

        result = extract_features_from_url(url)
        if not result or result.get("product_name") == "Error": return None

        # 2. 분석 (위험도 & 선호도)
        # 💡 result 안에 이미 모든 심리 축과 정규화된 데이터가 있어서 그대로 활용!
        risk_res = analyze_product_risk(result, model_ready_code)
        pref_out = infer_all(item_json=result, persona_type=model_ready_code, prior_dir=PRIOR_MODEL_DIR)
        
        impulse_score = int(risk_res.get('total_score', 0))
        total_pref_score = int(pref_out['total_score'])

        # 3. DB 저장 (상품 확인 및 생성)
        product = db.query(Product).filter(Product.product_name == result['product_name']).first()
        if not product:
            product = Product(
                product_img=result.get('product_img', ''),
                product_name=result.get('product_name', 'Unknown'),
                platform=result.get('platform', 'Unknown'),
                category=result.get('category', '기타'),
                price=int(result.get('discounted_price', 0)), # ✅ 키값 통일
                discount_rate=float(result.get('discount_rate', 0)),
                is_direct_shipping=bool(result.get('is_direct_shipping', 0)),
                review_count=int(result.get('review_count', 0)),
                review_score=float(result.get('review_score', 0.0)), # ✅ rating -> review_score
                product_likes=str(result.get('product_likes', '0')),
                **{col: result.get(col, 0) for col in ["sim_temptation", "sim_trend_hype", "sim_fit_anxiety", "sim_quality_logic", "sim_bundle", "sim_confidence"]}
            )
            db.add(product); db.flush()

        # 4. 유저-상품 매핑 저장
        user_prod = UserProduct(
            user_id=user.user_id, product_id=product.product_id,
            user_type=user_persona_code, risk_score_1=impulse_score,
            status="IN_PROGRESS", preference_score=total_pref_score
        )
        db.add(user_prod); db.commit()

        # 캐시용 데이터 조립
        details = {
            "top_2_causes": risk_res.get('top_2_causes', []),
            "prior_reasons": pref_out.get('prior_reason_top2', []),
            "personal_reasons": pref_out.get('personal_reason_top2', []),
            "prior_score": pref_out.get('prior_score', 0),
            "personal_score": pref_out.get('personal_score', 0),
            "personal_reason_type": pref_out.get('personal_reason_type', 'neutral')
        }
    
        # Redis에 저장 (3600초 = 1시간 유지)
        cache_key = f"analysis:{user.user_id}:{product.product_id}"
        redis_client.setex(cache_key, 3600, json.dumps(details))

        # 5. 프롬프트 데이터 조립
        prompt_data = {
            "user_context": {"persona_type": user_persona_code, "target_style": getattr(user, 'chu_gu_me', '심플'), "n_effective": pref_out["n_effective"]},
            "analysis_result": {"total_prefer_score": total_pref_score, "impulse_score": impulse_score, "alpha_value": pref_out["alpha"]},
            "prior_analysis": {"score": pref_out["prior_score"], "top_reasons": [{"feature": r[0], "value": r[1]} for r in pref_out["prior_reason_top2"]]},
            "personal_analysis": {"score": pref_out["personal_score"], "reason_type": pref_out["personal_reason_type"], "top_reasons": [{"feature": r[0], "value": r[1]} for r in pref_out["personal_reason_top2"]]},
            "impulse_block": {"score": impulse_score, "label": risk_res["risk_label"], "level": risk_res["risk_level"], "top_causes": [{"name": c["feature_name"], "detail": c["detail"]} for c in risk_res["top_2_causes"]]}
        }

        # 6. 터미널 리포트 출력 (prompt_data를 추가로 넘겨줌!)
        print_analysis_report(user.user_id, user_persona_code, product.product_name, pref_out, risk_res, prompt_data)

        return prompt_data

    except Exception as e:
        db.rollback()
        print(f"❌ 에러 발생:\n{traceback.format_exc()}")
        return None

import json

def print_analysis_report(user_id, persona, p_name, pref, risk, prompt_data):
    """터미널에 분석 결과와 프롬프트 주입 데이터를 통째로 출력"""
    print("\n" + "="*80)
    print(f" 🚀 [SYSTEM REPORT] USER: {user_id} | PERSONA: {persona}")
    print(f" 📦 PRODUCT: {p_name}")
    print("="*80)

    # 1. 간단 요약
    print(f" [SUMMARY]")
    print(f" - Risk Score  : {risk['total_score']}점 ({risk['risk_label']})")
    print(f" - Pref. Score : {pref['total_score']}점 (Alpha: {pref['alpha']:.2f})")
    print("-" * 80)

    # 2. 프롬프트 주입 데이터 (JSON 형태로 예쁘게 출력)
    print(f" 📝 [PROMPT INJECTION DATA]")
    # indent=4를 주면 터미널에서 계층 구조가 한눈에 들어와!
    prompt_json = json.dumps(prompt_data, indent=4, ensure_ascii=False)
    print(prompt_json)
    
    print("-" * 80)
    print(f" ✅ 분석 및 프롬프트 준비 완료 (Timestamp: {datetime.datetime.now().strftime('%H:%M:%S')})")
    print("="*80 + "\n")

async def get_chat_response(db: Session, user_id: int, product_id: int, user_answers: dict, user_input: str, history: list = []):
   # 1. DB 레코드 조회
    record = db.query(UserProduct).filter(
        UserProduct.user_id == user_id,
        UserProduct.product_id == product_id
    ).order_by(UserProduct.created_at.desc()).first()

    # 🚩 '...'을 실제 조건으로 교체!
    product = db.query(Product).filter(Product.product_id == product_id).first()
    user = db.query(User).filter(User.user_id == user_id).first()

    if not record or not product or not user:
        return "데이터를 불러오는 데 실패했어. 다시 시도해줄래? 🧐"

    if not record:
        return "분석 기록이 없네! 다시 URL을 넣어줄래? 🧐"

    # 🚩 [핵심: 레디스에서 상세 데이터 꺼내기]
    cache_key = f"analysis:{user_id}:{product_id}"
    cached_raw = redis_client.get(cache_key)
    
    if not cached_raw:
        # 캐시가 없으면(만료됐으면) 최소한의 기본값이라도 세팅해
        print(f"⚠️ 캐시 만료됨: {cache_key}")
        details = {
            "top_2_causes": [], 
            "prior_reasons": [], 
            "personal_reasons": [],
            "prior_score": 0,
            "personal_score": 0
        }
    else:
        details = json.loads(cached_raw)

    # 2. 모드 결정 및 가이드 데이터 추출
    mode = determine_mode([
        {"q_id": 1, "answer_id": user_answers.get('q1')},
        {"q_id": 2, "answer_id": user_answers.get('q2')},
        {"q_id": 3, "answer_id": user_answers.get('q3')}
    ])
    
    # 모드에 따른 점수 및 레벨 산출 (impulse_score 기반 5단계 매핑)
    from .logic.impulse_calculator import RISK_LEVELS
    impulse_score = record.risk_score_1
    
    # RISK_LEVELS 범위에 맞춰 level_num 결정 (1~5)
    level_num = 1
    for low, high, label, level in RISK_LEVELS:
        if low <= impulse_score <= high:
            level_num = level
            break

    from .constants import STRATEGY_MATRIX, IMPULSE_GUIDE_DATA
    guide_info = STRATEGY_MATRIX[mode][level_num]
    mode_guides = IMPULSE_GUIDE_DATA[mode]["features"]

    # 4. [선호도 블록] 맞춤 텍스트 매핑 로직
    persona_suffix = record.user_type[-1].lower() # 't' or 'm'
    persona_prefix = "default_" if persona_suffix == 't' else "myway_"
    
    # Personal 텍스트 사전 선택
    p_type = details.get('personal_reason_type', 'positive')
    personal_text_dict = PERSONAL_RISK_TEXT if p_type == 'risk' else PERSONAL_POS_TEXT

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
        "mode_block": { "current_mode": mode },

        "impulse_block": {
            "impulse_score": record.risk_score_1,
            "impulse_reason_top2": [
                {
                    "feature_key": cause["feature_key"],
                    "value": cause.get("detail", ""),
                    "guide": mode_guides.get(
                            f"{cause['feature_key']}_{persona_suffix}" if cause["feature_key"] in ["review_count", "product_like"] else cause["feature_key"],
                            "이 부분 주의깊게 봐!"
                        )
                } for cause in details.get('top_2_causes', [])
            ]
        },
        
        "preference_block": {
            "total_score": record.preference_score,
            "mixing": { "preference_priority": DEFAULT_VALUES["preference_priority"] },
            "prior_score": details.get('prior_score', 0),
            "prior_reason_top2": [
                {
                    "feature_key": r[0],
                    "value": r[1],
                    "guide": PRIOR_TEXT.get(
                        f"{persona_prefix}review_count" if r[0] == "review_count" else (
                            "product_likes" if r[0] == "product_like" else r[0]
                        ),
                        f"너랑 비슷한 유형은 '{FEATURE_KO.get(r[0], r[0])}' 조건이 만족스러우면 고민이 줄어드는 편이야."
                    )
                } for r in details.get('prior_reasons', [])
            ],
            "personal_score": details.get('personal_score', 0),
            "personal_reason_top2": [
                {
                    "feature_key": r[0],
                    "value": r[1],
                    "guide": personal_text_dict.get(
                        f"{persona_prefix}{r[0]}" if r[0] == "review_count" else (
                            f"{persona_prefix}product_likes" if r[0] == "product_like" else r[0]
                        ),
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
            "mode": mode,
            "level": level_num,
            "label": guide_info["label"],
            "goal": guide_info["goal"],
            "rationale": guide_info["rationale"],
            "stance": guide_info["stance"],
            "tone": guide_info["tone"],
            "strategy": guide_info["strategy"]
        }
    }

    # 4. 이제 이 JSON을 빌더에게 던짐!
    builder = TobabaPromptBuilder(final_input_json, current_step=1, user_input=user_input, history=history)
    
    try:
        model = genai.GenerativeModel(
            model_name='models/gemini-2.0-flash', # 리스트에 있는 이름으로 교체!
            system_instruction=builder.get_system_instruction()
        )
        response = model.generate_content(builder.build_dynamic_context())
        bot_msg, _, _ = parse_llm_response(response.text)
        return bot_msg
        
    except Exception as e:
        print(f"❌ Gemini 에러: {e}")
        return "미안, 내 뇌에 잠깐 렉 걸렸어. 다시 말해줄래?"

# --- 설문 숫자를 문장으로 바꿔주는 도우미 함수들 ---

def get_q1_text(val: int):
    mapping = {
        1: "방금 담았어 / 1시간 이내",
        2: "1~2일 이내",
        3: "일주일 이내",
        4: "일주일 이상",
        5: "한달 이상"
    }
    return mapping.get(val, "방금 전")

def get_q2_text(val: int):
    mapping = {
        1: "사도 되는지 확인받고 싶어서",
        2: "그냥 이 옷 어떤가 궁금해서",
        3: "오래 고민했는데 결정이 안 나서",
        4: "사고나서 후회할까봐 걱정돼서"
    }
    return mapping.get(val, "궁금해서")

def get_q3_text(val: int):
    mapping = {
        1: "사고싶긴 한데 비슷한 옷들이 많아서 고민이 돼",
        2: "장바구니 옷 중에 이게 제일 마음에 들어",
        3: "이미 코디까지 다 생각해 둬서 사면 잘 입을 것 같아",
        4: "다 좋은데.. 혹시 더 나은 게 있을까봐 불안해"
    }
    return mapping.get(val, "확신 없음")

# get_qc_text는 이미 정의되어 있을 수도 있지만, 확인 차 다시!
def get_qc_text(val: int):
    mapping = {
        1: "가성비",
        2: "시즌오프 세일 / 품절 임박",
        3: "요즘 유행템 / 연예인 착용",
        4: "소재 및 퀄리티",
        5: "MD/인플루언서 픽",
        6: "모델의 착용 핏",
        7: "빠른 배송 필요"
    }
    return mapping.get(val, "디자인")

import re

def parse_llm_response(text: str):
    """
    LLM 응답에서 [STEP_XXX: N] 등 대괄호로 된 모든 태그를 분리하고 본문만 남김
    """
    # 1. 숫자 단계 추출 (STEP_MOVED나 STEP_HELD 뒤의 숫자 찾기)
    step_match = re.search(r"\[STEP_(?:MOVED|HELD):\s*(\d+)\]", text)
    next_step = int(step_match.group(1)) if step_match else 1 # 기본값 1
    
    # 2. 보류 여부 추출
    is_held = "[STEP_HELD" in text or "[IS_HELD: TRUE]" in text
    
    # 3. 🔥 대괄호([])로 감싸진 모든 시스템 태그 삭제
    # 이 정규식은 [내용] 형태를 찾아서 통째로 지워줘.
    clean_msg = re.sub(r"\[.*?\]", "", text)
    clean_msg = clean_msg.strip()
    
    return clean_msg, next_step, is_held