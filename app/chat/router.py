from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from app.core.database import get_db
from . import service

router = APIRouter(prefix="/api/chat", tags=["chat"])

@router.post("/start")
async def start_chat(
    product_url: str, 
    user_id: int, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db)
):
    # Phase 0: 상품 분석 병렬 처리 시작
    # background_tasks.add_task(service.parse_and_save_product, product_url, user_id)
    
    # Phase 0: 즉시 공통 질문 리스트 반환
    initial_questions = [
        "이 옷, 언제부터 눈독 들이고 있었어?",
        "지금 이거 안 사면 당장 내일 큰일 나?"
    ]
    return {
        "message": "분석을 시작할게. 그동안 몇 가지만 물어보자!",
        "questions": initial_questions,
        "phase": "PHASE_0"
    }

@router.post("/message")
async def chat_message(
    user_id: int, 
    product_id: int, 
    message: str, 
    db: Session = Depends(get_db)
):
    # Phase 1 & 2: 데이터 병합 및 LLM 답변 호출
    # 여기서 service.get_chat_response가 실행됩니다.
    response_text = await service.get_chat_response(db, user_id, product_id, message)
    
    return {"reply": response_text}