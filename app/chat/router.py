from http.client import HTTPException

from app.chat.logic.impulse_calculator import analyze_product_risk
from app.products.models import UserProduct
from app.users.models import User
from app.users.router import get_current_user
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from app.core.database import get_db
from . import service
import google.generativeai as genai  # ✅ 이 줄을 추가해줘!

router = APIRouter(prefix="/api/chat", tags=["chat"])

@router.post("/start")
async def start_chat(
    product_url: str, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # ✅ 토큰으로 유저 식별
):
    # 1. 페르소나 정리
    user_persona_code = service.clean_persona_code(current_user)

    # 2. 임시 UserProduct 레코드 먼저 생성 (product_id는 0으로 둠)
    user_prod = UserProduct(
        user_id=current_user.user_id,
        product_id=0,
        user_type=user_persona_code,
        status="PENDING"
    )
    db.add(user_prod)
    db.commit()
    db.refresh(user_prod)

    # 3. 백그라운드 태스크에 user_product_id 전달
    background_tasks.add_task(
        service.parse_and_save_product, 
        db, 
        product_url, 
        current_user,
        user_prod.user_product_id  # ✅ 새로 추가됨
    )

    # 4. 유저에게는 user_product_id와 설문지 전달
    return {
        "status": "ANALYSIS_STARTED",
        "user_product_id": user_prod.user_product_id,
        "survey_config": {
            "q1": "이거 장바구니/찜에 담은 지 얼마나 됐어?",
            "q2": "나한테 왜 연락한 거야?",
            "q3": "이 옷, 이미 거의 사기로 마음 정한 상태야? 아니면 아직 확신이 부족해?",
            "qc": "이 옷의 어떤 점이 네 마음을 뺏었어?"
        },
        "message": "분석 시작했어! 그전에 네 상태 좀 체크해보자."
    }

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.chat.schemas import SurveyRequest  # 아까 만든 Pydantic 모델
from app.chat import service

@router.post("/finalize-survey/{user_product_id}")
async def finalize_survey(
    user_product_id: int,
    request: SurveyRequest,  # ✅ 이제 additionalProp1 대신 q1, q2.. 딱 뜸!
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    # 1. Pydantic 모델을 dict로 변환 (q1, q2, q3, qc 포함)
    user_answers = request.model_dump()

   # 2. 이 유저가 요청한 특정 상품 분석 기록 찾기
    last_request = db.query(UserProduct).filter(
        UserProduct.user_product_id == user_product_id,
        UserProduct.user_id == current_user.user_id
    ).first()

    if not last_request:
        raise HTTPException(status_code=404, detail="요청한 상품 기록이 없어요!")

    # 만약 '분석 완료'를 나타내는 별도의 필드(예: is_analyzed)가 있다면 여기서 체크
    # if not last_request.is_analyzed:
    #     raise HTTPException(status_code=202, detail="아직 데이터 분석 중이에요!")

    print(f"🚀 DEBUG: 불러온 상품 ID -> {last_request.product_id}")
    
    # 3. 챗봇 답변 생성 시작
    # 서비스 레이어에서 이제 언니가 원했던 그 '최종 JSON' 형식을 만들어서 Gemini를 호출함
    first_response = await service.get_chat_response(
        db=db, 
        user_id=current_user.user_id, 
        user_product_id=user_product_id, 
        user_answers=user_answers, 
        user_input="설문 완료!" # 첫 진입이므로 고정 메시지 전달
    )
    
    return {"reply": first_response}
