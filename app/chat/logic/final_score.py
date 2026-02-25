import json
from sqlalchemy.orm import Session
from app.products.models import UserProduct

def get_scores_from_prompt_data(db: Session, user_product_id: int):
    """
    user_product 테이블의 prompt_data(JSON)에서 
    impulse_score와 preference_score(total_score)를 추출하여 반환합니다.
    """
    record = db.query(UserProduct).filter(UserProduct.user_product_id == user_product_id).first()
    
    if not record or not record.prompt_data:
        return None

    try:
        data = json.loads(record.prompt_data)
        
        # prompt_data JSON 구조에서 점수 추출
        # (init_chat_session에서 저장하는 final_input_json 구조 기준)
        impulse_score = data.get("impulse_block", {}).get("impulse_score")
        preference_score = data.get("preference_block", {}).get("total_score")
        
        return {
            "impulse_score": impulse_score,
            "preference_score": preference_score
        }
    except json.JSONDecodeError:
        return None

def compute_final_score(impulse_score: int, preference_score: int, attitude_code: str, mode: str) -> int:
    """
    사용자 성향과 충동/취향 점수를 종합하여 최종 점수(purchase pressure)를 계산합니다.
    (AI/Final_score.py에서 이관된 로직)
    """
    # 1. 기본 점수: 충동 점수 60% + 취향 점수 40%
    base = 0.6 * impulse_score + 0.4 * preference_score

    # 2. 유저 태도 코드(attitude_code) 보정
    code_map = {"C1": -10, "N0": 0, "W1": 7, "W2": 15}
    base += code_map.get(attitude_code, 0)

    # 3. 현재 모드(Brake, Decider)에 따른 최종 보정
    # W2(무조건 구매)인 경우 모드 보정 적용 X (어차피 살 거니까)
    if attitude_code != "W2":
        if mode == "BRAKE":
            base *= 1.1
        elif mode == "DECIDER":
            base *= 0.9

    return max(0, min(100, round(base)))