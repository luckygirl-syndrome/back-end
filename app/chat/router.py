from http.client import HTTPException

from app.products.models import UserProduct
from app.users.models import User
from app.users.router import get_current_user
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from app.core.database import get_db
from . import service

router = APIRouter(prefix="/api/chat", tags=["chat"])

@router.post("/start")
async def start_chat(
    product_url: str, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # ✅ 이제 토큰 없으면 호출 자체가 안 됨
):
    # current_user.user_id를 안전하게 사용
    background_tasks.add_task(
        service.parse_and_save_product, 
        db, 
        product_url, 
        current_user.user_id
    )

    # [Phase 0] 질문을 AI가 하는 게 아니라, 정해진 공통 질문 세트를 프론트에 전달
    # 프론트는 이걸 받아서 유저에게 설문 UI(라디오 버튼 등)를 보여주게 됨
    return {
        "status": "ANALYSIS_STARTED",
        "survey_config": {
            "q1": "이거 장바구니/찜에 담은 지 얼마나 됐어?",
            "q2": "나한테 왜 연락한 거야?)",
            "q3": "이 옷, 이미 거의 사기로 마음 정한 상태야? 아니면 아직 확신이 부족해?",
            "qc": "이 옷의 어떤 점이 네 마음을 뺏었어?"
        },
        "message": "분석 시작했어! 그전에 네 상태 좀 체크해보자."
    }

# app/chat/router.py

@router.post("/finalize-survey")
async def finalize_survey(
    user_answers: dict, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # ✅ JWT로 유저 자동 식별
):
    # 1. 이 유저가 가장 최근에 분석 요청한 상품 찾기
    last_request = db.query(UserProduct).filter(
        UserProduct.user_id == current_user.user_id
    ).order_by(UserProduct.created_at.desc()).first()

    if not last_request:
        raise HTTPException(status_code=404, detail="분석 중인 상품이 없어요!")

    # 2. 찾은 product_id를 가지고 챗봇 답변 생성
    first_response = await service.get_chat_response(
        db=db, 
        user_id=current_user.user_id, 
        product_id=last_request.product_id, # ✅ 서버가 직접 찾아낸 ID 전달
        user_answers=user_answers, 
        user_input="설문 완료!"
    )
    
    return {"reply": first_response}