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
    # [Phase 0] 상품 분석 병렬 처리 (서버는 뒤에서 열일 시작)
    background_tasks.add_task(service.parse_and_save_product, product_url, user_id)
    
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

@router.post("/finalize-survey")
async def finalize_survey(
    user_id: int, 
    user_answers: dict,  # q1, q2, q3, qc가 담긴 딕셔너리
    db: Session = Depends(get_db)
):
    # [Phase 1 & 2] 설문이 끝나자마자 로직 게이트 통과 후 '첫 발화' 생성
    # 유저는 답변을 완료하자마자 또바바의 팩폭(Step 1)을 듣게 됨
    first_response = await service.get_chat_response(
        db=db, 
        user_id=user_id, 
        user_answers=user_answers, 
        user_input="설문 완료! 이제 판결해줘." # 트리거 문구
    )
    
    return {"reply": first_response}