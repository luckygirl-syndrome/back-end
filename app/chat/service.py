import os
from sqlalchemy.orm import Session
from app.users.models import User
from app.products.models import Product, UserProduct # 파일명이 models.py 인지 확인!
from .prompt import TobabaPromptBuilder
import google.generativeai as genai
from .constants import IMPULSE_GUIDE_DATA
import joblib

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# 챗봇 설명용 한글 매핑
FEATURE_KO = {
    'discount_rate': '할인율', 'review_count': '리뷰 수', 'review_score': '평점',
    'product_like': '찜 수', 'shipping_info': '배송 정보', 'free_shipping': '무료 배송',
    'sim_trend_hype': '유행/대란 키워드', 'sim_temptation': '자극적 홍보 문구',
    'sim_fit_anxiety': '핏/체형 보정 문구', 'sim_quality_logic': '소재/퀄리티 강조',
    'sim_bundle': '1+1/묶음 할인', 'sim_confidence': 'MD추천/보증'
}

def get_logic_gate_mode(user_answers: dict):
    # 1. 질문별 스코어 테이블 설정
    # (Brake, Decider) 순서
    q1_table = {1: (2, 0), 2: (1, 0), 3: (0, 1), 4: (0, 2), 5: (0, 3)}
    q2_table = {1: (2, 0), 2: (1, 0), 3: (0, 2), 4: (0, 1)}
    q3_table = {1: (0, 1), 2: (1, 0), 3: (2, 0), 4: (0, 2)}
    
    # 2. 총점 계산
    b_score = q1_table[user_answers['q1']][0] + q2_table[user_answers['q2']][0] + q3_table[user_answers['q3']][0]
    d_score = q1_table[user_answers['q1']][1] + q2_table[user_answers['q2']][1] + q3_table[user_answers['q3']][1]

    # 3. [최종 로직 결정] 동점이면 DECIDER!
    if b_score > d_score:
        mode = "BRAKE"
    elif d_score > b_score:
        mode = "DECIDER"
    else:
        mode = "DECIDER" # 동점일 때 처리
        
    return mode, b_score, d_score

async def get_chat_response(db: Session, user_id: int, user_answers: dict, user_input: str, history: list = []):
    # 1. DB 유저 정보
    user = db.query(User).filter(User.user_id == user_id).first()
    
    # 2. 로직 게이트 (모드/점수 확정)
    mode, b_score, d_score = get_logic_gate_mode(user_answers)
    
    # QC 매칭
    qc_map = {1:"가성비", 2:"시즌오프 세일 / 품절 임박", 3:"요즘 유행템 같아서, 연예인이 입었대서", 4:"퀄리티가 좋을 것 같아서", 5:"MD, 인플루언서가 픽했대서", 6:"모델이 입은 핏이 예뻐서", 7:"배송이 빨리 와야해서"}
    key_appeal_text = qc_map.get(user_answers['qc'], "디자인")
    
    # 3. 레벨 확정 및 가이드 데이터 추출
    level_num = min(5, max(1, b_score))
    level_key = f"Level {level_num}"
    
    # [핵심] 매핑 없이 해당 레벨의 모든 가이드 문장 셋을 가져옴
    # 언니가 constants.py에 정의한 "잠깐! 너 지금..." 같은 문장들이 여기 다 들어있음
    level_guides = IMPULSE_GUIDE_DATA[level_key]

    # 4. 언니 빌더용 데이터 조립 (Input JSON)
    data = {
        "user_context": {
            "persona_type": user.persona_type,
            "target_style": "유저의 추구미"
        },
        "product_context": {
            "name": "상의", 
            "brand": "아캄",
            "price": 100000
        },
        "mode_block": {"current_mode": mode},
        "impulse_block": {
            "impulse_score": b_score * 20,
            # 매핑 로직 삭제: 레벨에 해당하는 문장 딕셔너리를 통째로 넘김
            # LLM이 'impulse_reason_top2' 내의 문장들을 보고 유저 답변(qc)과 대조해서 발화함
            "impulse_reason_top2": [
                {"feature_key": k, "guide": v} for k, v in level_guides["features"].items()
            ]
        },
        "preference_block": {
            "total_score": d_score * 20,
            "personal_score": 50,
            "mixing": {"preference_priority": "personal"}
        },
        "conversation_block": {
            "key_appeal": key_appeal_text,
            "cart_duration": f"선택지 {user_answers['q1']}번 기간"
        },
        "strategy_matrix": {
            "goal": level_guides["goal"],
            "strategy": level_guides["strategy"]
        }
    }

    # 5. 프롬프트 빌드 및 실행
    builder = TobabaPromptBuilder(data, user_input=user_input, history=history)
    model = genai.GenerativeModel(
        model_name='gemini-1.5-flash',
        system_instruction=builder.get_system_instruction()
    )
    
    response = model.generate_content(builder.build_dynamic_context())
    return response.text

import datetime
from sqlalchemy.orm import Session
from app.products.parsers.item_parser import extract_features_from_url
from app.products.models import Product, UserProduct # 모델 경로 확인

import json
from app.chat.logic.impulse_calculator import analyze_product_risk # 아까 만든 로직 임포트

# 로직 임포트
from app.chat.logic.impulse_calculator import analyze_product_risk
from app.chat.logic.final_prefer import infer_all # 👈 선호도 로직 추가
import os
import datetime
import json
from sqlalchemy.orm import Session
from app.products.parsers.item_parser import extract_features_from_url
from app.products.models import Product, UserProduct

# 모델 아티팩트 경로 (절대 경로 추천)
PRIOR_MODEL_DIR = "/Users/nau/Documents/GitHub/Back-end/models/artifacts_prior/"

def parse_and_save_product(db: Session, url: str, user: User):
    try:
        # 1. 페르소나 추출 및 하이픈 형태(D-S-T)로 만들기
        persona_raw = getattr(user, 'persona_type', "D-S-T")
        
        if isinstance(persona_raw, str) and persona_raw.startswith('{'):
            try:
                persona_data = json.loads(persona_raw)
                persona_raw = persona_data.get('persona_code', 'D-S-T')
            except:
                persona_raw = "D-S-T"

        # 🔥 핵심: DST가 들어오면 D-S-T로, D-S-T면 그대로!
        temp_code = str(persona_raw).replace("-", "").upper() # 일단 다 합치고
        if len(temp_code) == 3:
            # DST -> D-S-T 변환
            user_persona_code = f"{temp_code[0]}-{temp_code[1]}-{temp_code[2]}"
        else:
            user_persona_code = temp_code # 이미 형식이 맞으면 그대로

        print(f"DEBUG: 모델이 좋아하는 최종 코드 -> [{user_persona_code}]")

        # 2. 크롤링 수행
        result = extract_features_from_url(url)
        if not result or result.get("product_name") == "Error":
            return None

        # ---------------------------------------------------------
        # [Step 1] 위험도 분석 (Impulse) -> 대화 모드(Brake/Decider) 결정용
        # ---------------------------------------------------------
        risk_analysis = analyze_product_risk(result, user_persona_code)
        impulse_score = int(risk_analysis.get('total_score', 0))

        # ---------------------------------------------------------
        # [Step 2] 선호도 분석 (Preference) -> 대화의 근거/공감용
        # ---------------------------------------------------------
        pref_item_input = {
            "discount_rate": float(result.get('discount_rate', 0)),
            "review_score": float(result.get('rating', 0)),
            "review_count": int(result.get('review_count', 0)),
            "product_likes": int(result.get('product_likes', 0)),
            "platform": result.get('platform', 'Unknown'),
            "is_direct_shipping": 1.0 if result.get('is_direct_shipping') else 0.0,
            "free_shipping": 1.0 if result.get('free_shipping') else 0.0,
            "sim_quality_logic": int(result.get('sim_quality_logic', 0)),
            "sim_trend_hype": int(result.get('sim_trend_hype', 0)),
            "sim_temptation": int(result.get('sim_temptation', 0)),
            "sim_fit_anxiety": int(result.get('sim_fit_anxiety', 0)),
            "sim_bundle": int(result.get('sim_bundle', 0)),
            "sim_confidence": int(result.get('sim_confidence', 0))
        }

        # [Step 2] 선호도 분석 (Preference)
        # 이제 이 코드로 분석 실행!
        pref_out = infer_all(item_json=result, persona_type=user_persona_code, prior_dir=PRIOR_MODEL_DIR)
        total_pref_score = int(pref_out['total_score']) # 👈 이게 선호도

        prior_score     = pref_out["prior_score"]
        prior_reasons   = pref_out["prior_reason_top2"]     # 리스트 형태
        personal_score  = pref_out["personal_score"]
        personal_type   = pref_out["personal_reason_type"]  # positive/risk/neutral
        personal_reasons= pref_out["personal_reason_top2"]   # 리스트 형태
        alpha           = pref_out["alpha"]
        n_eff           = pref_out["n_effective"]

        # 1. 위험도 분석 결과 상세 추출 (analyze_product_risk의 리턴값)
        risk_label    = risk_analysis["risk_label"]
        risk_level    = risk_analysis["risk_level"]
        risk_causes   = risk_analysis["top_2_causes"]

        # ---------------------------------------------------------
        # [Step 3] DB 저장
        # ---------------------------------------------------------
        product = db.query(Product).filter(Product.product_name == result['product_name']).first()
        if not product:
            product = Product(
                product_name=product_name,
                platform=result.get('platform', 'Unknown'),
                category=result.get('category', '기타'),
                price=int(result.get('price', 0)),
                discount_rate=float(result.get('discount_rate', 0)),
                is_direct_shipping=bool(result.get('is_direct_shipping', False)),
                free_shipping=bool(result.get('free_shipping', False)),
                review_count=int(result.get('review_count', 0)),
                review_score=float(result.get('rating', 0)),
                product_likes=str(result.get('product_likes', '0')),
                preference_score=total_pref_score,
                sim_temptation=result.get('sim_temptation', 0),
                sim_trend_hype=result.get('sim_trend_hype', 0),
                sim_fit_anxiety=result.get('sim_fit_anxiety', 0),
                sim_quality_logic=result.get('sim_quality_logic', 0),
                sim_bundle=result.get('sim_bundle', 0),
                sim_confidence=result.get('sim_confidence', 0),
                created_at=datetime.datetime.now()
            )
            db.add(product)
            db.flush()

        user_prod_entry = UserProduct(
            user_id=user.user_id,         
            product_id=product.product_id,
            user_type=user_persona_code,
            risk_score_1=impulse_score,    # 위험도 (Brake 수위)
            risk_score_2=total_pref_score, # 선호도 (공감/설득 근거)
            status="COMPLETED",
            created_at=datetime.datetime.now()
        )
        db.add(user_prod_entry)
        db.commit()

        # ---------------------------------------------------------
        # [Step 4] 프롬프트 빌더용 데이터 구성 (핵심!)
        # ---------------------------------------------------------
        current_mode = "BRAKE" if impulse_score >= 50 else "DECIDER"
        
        prompt_data = {
            "user_context": {
                "persona_type": user_persona_code,
                "target_style": getattr(user, 'target_style', '심플/캐주얼'),
                "n_effective": n_eff
            },
            "analysis_result": {
                "total_prefer_score": total_pref_score,
                "impulse_score": impulse_score,
                "alpha_value": alpha,
                "current_mode": current_mode
            },
            "prior_analysis": {
                "score": prior_score,
                "top_reasons": [
                    {"feature": r[0], "value": r[1]} for r in prior_reasons # 👈 r[1]이 이제 '값'임
                ]
            },
            "personal_analysis": {
                "score": personal_score,
                "reason_type": personal_type,
                "top_reasons": [
                    {"feature": r[0], "value": r[1]} for r in personal_reasons # 👈 여기도 '값'으로 매칭
                ]
            },
            "impulse_block": {
                "score": impulse_score,
                "label": risk_label,
                "level": risk_level,
                "top_causes": [
                    {
                        "name": c["feature_name"],
                        "detail": c["detail"]
                    } for c in risk_causes
                ]
            },
            "strategy": {
                "goal": "충동 억제" if current_mode == "BRAKE" else "구매 확신",
                "main_logic": "personal" if alpha < 0.5 else "prior"
            }
        }

        # [Step 5] Terminal Report (최종 정리)
        print("\n" + "-"*60)
        print(f" SYSTEM ANALYSIS REPORT | USER: {user.user_id} | PERSONA: {user_persona_code}")
        print("-" * 60)
        print(f" [PRODUCT] {product.product_name}")
        print(f" [STATUS ] Mode: {current_mode} | Tracking: {n_eff} items")
        print("-" * 60)

        # 1. RISK ANALYSIS (위험도)
        # detail(수치)이 있을 때만 괄호를 붙이고, 없으면 이름만!
        risk_details = [
            f"{c['feature_name']}({c['detail']})" if c.get('detail') else c['feature_name'] 
            for c in risk_causes
        ]
        print(f" 1. RISK SCORE      : {impulse_score} / 100 ({risk_label})")
        print(f"    - Top Causes    : {', '.join(risk_details)}")
        
        # 2. PREFERENCE ANALYSIS (선호도)
        # r[1](수치)이 있을 때만 괄호를 붙이고, 없으면 이름만!
        prior_details = [
            f"{FEATURE_KO.get(r[0], r[0])}({r[1]})" if r[1] else FEATURE_KO.get(r[0], r[0]) 
            for r in prior_reasons
        ]
        # 퍼스널 데이터가 있을 때만 처리
        pers_details = [
            f"{FEATURE_KO.get(r[0], r[0])}({r[1]})" if r[1] else FEATURE_KO.get(r[0], r[0]) 
            for r in personal_reasons
        ] if personal_reasons else [""]

        print(f" 2. PREFERENCE SCORE: {total_pref_score} / 100")
        print(f"    - Alpha Weight  : {alpha:.2f} (Group vs Personal)")
        print(f"    - Group Reasons : {', '.join(prior_details)}")
        print(f"    - Pers. Reasons : {', '.join(pers_details)} ({personal_type})")
        print("-" * 60 + "\n")

        return prompt_data

    except Exception as e:
        db.rollback()
        print(f"❌ 에러 발생: {e}")
        return None