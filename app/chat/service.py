import os
from sqlalchemy.orm import Session
from app.users.models import User
from app.products.models import Product, UserProduct # 파일명이 models.py 인지 확인!
from .prompt import TobabaPromptBuilder
import google.generativeai as genai
from .constants import IMPULSE_GUIDE_DATA

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

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
        # 1. 유저 페르소나 코드 추출 (SDM, DAM 등)
        user_id = user.user_id
        persona_obj = getattr(user, 'persona_type', None)
        if isinstance(persona_obj, dict):
            user_persona_code = persona_obj.get("persona_type", "D-S-T")
        else:
            user_persona_code = str(persona_obj)[:3] if persona_obj else "D-S-T"

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
        pref_out = infer_all(item_json=pref_item_input, persona_type=user_persona_code, prior_dir=PRIOR_MODEL_DIR)
        total_pref_score = int(pref_out['total_score']) # 👈 이게 선호도

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
            user_id=user_id,
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
        # 위험도에 따른 모드 결정 (70점 이상이면 강력 제동)
        current_mode = "BRAKE" if impulse_score >= 50 else "DECIDER"
        
        prompt_data = {
            "user_context": {
                "persona_type": user_persona_code,
                "target_style": getattr(user, 'target_style', '심플/캐주얼')
            },
            "product_context": {
                "name": product.product_name,
                "price": product.price,
                "brand": result.get('brand', 'Unknown')
            },
            "mode_block": {"current_mode": current_mode},
            "impulse_block": {
                "impulse_score": impulse_score,
                # 위험 요소 상위 2개 추출
                "impulse_reason_top2": [
                    {"feature_key": r[0], "guide": "위험 요인"} for r in risk_analysis.get('top_reasons', [])[:2]
                ]
            },
            "preference_block": {
                "total_score": total_pref_score,
                "personal_score": pref_out['personal_score'],
                "preference_priority": pref_out['alpha'] < 0.5 and "personal" or "prior",
                # 선호 요소 상위 2개 추출 (prior_reason_top3 활용)
                "prior_reason_top2": [
                    {"feature_key": r[0], "guide": "유저 그룹 선호 요인"} for r in pref_out['prior_reason_top3'][:2]
                ],
                "personal_reason_top2": [
                    {"feature_key": r[0], "guide": "유저 개인 취향 일치"} for r in pref_out['personal_reason_top3'][:2]
                ]
            },
            "conversation_block": {
                "cart_duration": "방금 막",
                "key_appeal": result.get('key_appeal', '디자인/핏')
            },
            "strategy_matrix": {
                "goal": current_mode == "BRAKE" and "충동 억제" or "구매 확신",
                "strategy": "위험도와 선호도를 교차 분석하여 대응"
            }
        }

        print(f"✅ 분석 및 저장 완료 (Risk: {impulse_score}, Prefer: {total_pref_score})")
        return prompt_data

    except Exception as e:
        db.rollback()
        print(f"❌ 에러 발생: {e}")
        return None