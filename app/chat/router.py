"""
app/chat/router.py

HTTP 요청/응답 API 엔드포인트 정의.
비즈니스 로직이나 DB 쿼리 작성은 하지 않는다.
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.users.models import User
from app.users.router import get_current_user
from app.products.models import UserProduct
from .schemas import SurveyRequest, ChatMessageRequest, ChatMessageResponse
from . import service

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ──────────────────────────────────────────────
# 1. 채팅 시작 (상품 분석 요청)
# ──────────────────────────────────────────────
@router.post("/start")
async def start_chat(
    product_url: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """상품 URL을 받아 파싱을 시작하고 설문지를 반환."""
    background_tasks.add_task(
        service.parse_and_save_product,
        db,
        product_url,
        current_user,
    )

    return {
        "status": "ANALYSIS_STARTED",
        "survey_config": {
            "q1": "이거 장바구니/찜에 담은 지 얼마나 됐어?",
            "q2": "나한테 왜 연락한 거야?",
            "q3": "이 옷, 이미 거의 사기로 마음 정한 상태야? 아니면 아직 확신이 부족해?",
            "qc": "이 옷의 어떤 점이 네 마음을 뺏었어?",
        },
        "message": "분석 시작했어! 그전에 네 상태 좀 체크해보자.",
    }


# ──────────────────────────────────────────────
# 2. 설문 제출 → 세션 초기화 → 첫 응답
# ──────────────────────────────────────────────
@router.post("/finalize-survey")
async def finalize_survey(
    request: SurveyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """설문 응답을 받아 세션을 초기화하고 첫 챗봇 응답을 반환."""
    user_answers = request.model_dump()

    # 가장 최근 상품 분석 기록 찾기 (chat_id = user_product_id)
    last_request = (
        db.query(UserProduct)
        .filter(UserProduct.user_id == current_user.user_id)
        .order_by(UserProduct.created_at.desc())
        .first()
    )

    if not last_request:
        raise HTTPException(status_code=404, detail="요청한 상품 기록이 없어요!")

    chat_id = last_request.user_product_id
    print(f"🚀 DEBUG: chat_id(user_product_id) -> {chat_id}, product_id -> {last_request.product_id}")

    first_response = await service.init_chat_session(
        db=db,
        user_id=current_user.user_id,
        product_id=last_request.product_id,
        chat_id=chat_id,
        user_answers=user_answers,
    )

    return {"chat_id": chat_id, "reply": first_response}


# ──────────────────────────────────────────────
# 3. 채팅 메시지 (매 턴)
# ──────────────────────────────────────────────
@router.post("/{chat_id}/messages/", response_model=ChatMessageResponse)
async def send_message(
    chat_id: int,
    request: ChatMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """유저 메시지를 받아 LLM 응답을 반환."""
    result = await service.handle_message(
        db=db,
        chat_id=chat_id,
        user_input=request.message,
    )

    return ChatMessageResponse(message=result["message"])
