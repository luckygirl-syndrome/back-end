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

def parse_and_save_product(db: Session, url: str, user: User):
    try:
        # 1. 유저 정보 추출 (코드 정제)
        user_id = user.user_id
        persona_obj = getattr(user, 'persona_type', None)

        # ✅ 유저 페르소나 객체에서 "SDM" 같은 3글자 코드만 쏙 뽑아내기
        if isinstance(persona_obj, dict):
            user_persona_code = persona_obj.get("persona_type", "D-S-T")
        elif hasattr(persona_obj, 'persona_type'):
            user_persona_code = persona_obj.persona_type
        else:
            try:
                # 만약 문자열(JSON) 형태로 들어온 경우 파싱
                import json
                data = json.loads(persona_obj)
                user_persona_code = data.get("persona_type", "D-S-T")
            except:
                # 최후의 보루: 문자열에서 앞 3글자만 가져오기
                user_persona_code = str(persona_obj)[:3] if persona_obj else "D-S-T"

        print(f"🧐 분석 시작 - 유저: {user_id}, 최종 페르소나 코드: {user_persona_code}")
        
        # 2. 크롤링 및 분석 수행
        result = extract_features_from_url(url)
        if not result:
            print("❌ 분석 결과가 없습니다.")
            return

        # [Step 1] 위험도 분석 로직 실행 (정제된 코드 "SDM" 등 전달)
        # ✅ persona_obj 대신 user_persona_code를 넣으세요!
        risk_analysis = analyze_product_risk(result, user_persona_code)

        # [Step 2] products 테이블 저장 (UnboundLocalError 방지 로직)
        product_name = result.get('product_name', '이름 없는 상품')
        
        # ✅ 필독: 여기서 먼저 조회를 해서 product 변수를 확실히 만듭니다.
        product = db.query(Product).filter(Product.product_name == product_name).first()
        
        if not product:
            print(f"🆕 새 상품 등록: {product_name}")
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
                # ✅ ㅇㅇ핏 등 심리 축 저장 (KeywordAxisInfer 결과)
                sim_temptation=result.get('sim_temptation', 0),
                sim_trend_hype=result.get('sim_trend_hype', 0),
                sim_fit_anxiety=result.get('sim_fit_anxiety', 0),
                sim_quality_logic=result.get('sim_quality_logic', 0),
                sim_bundle=result.get('sim_bundle', 0),
                sim_confidence=result.get('sim_confidence', 0),
                created_at=datetime.datetime.now()
            )
            db.add(product)
            db.flush() # ID를 즉시 생성
        else:
            print(f"♻️ 기존 상품 정보 활용: {product_name}")

        # [Step 3] user_product 연결 테이블 생성
        user_prod_entry = UserProduct(
            user_id=user_id,
            product_id=product.product_id,
            requested_at=datetime.datetime.now(),
            
            # ✅ 작업 완료 시점이므로 현재 시간 기록
            completed_at=datetime.datetime.now(), 
            
            # ✅ 모델의 필드명 risk_score_1에 점수 저장
            risk_score_1=int(risk_analysis.get('total_score', 0)),
            
            # ✅ 유저의 페르소나 코드(SDM 등)를 user_type에 기록 (나중에 분석용)
            user_type=user_persona_code, 
            
            status="COMPLETED",
            is_purchased=0, # 기본값: 미구매
            created_at=datetime.datetime.now(),
            updated_at=datetime.datetime.now()
        )
        
        db.add(user_prod_entry)
        db.commit()
        
        print(f"✅ [Background] 최종 저장 성공! (상품ID: {product.product_id}, 점수: {risk_analysis.get('total_score')}점)")

    except Exception as e:
        db.rollback()
        print(f"❌ [Background] DB 작업 중 진짜 에러 발생: {str(e)}")