import os
from sqlalchemy.orm import Session
from app.users.models import User
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