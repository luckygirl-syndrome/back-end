from http.client import HTTPException

from app.chat.logic.impulse_calculator import analyze_product_risk
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
    current_user: User = Depends(get_current_user) # ✅ 토큰으로 유저 식별
):
    # 1. current_user에 sbti_code가 이미 있다고 가정합니다.
    # 만약 유저 테이블에 없다면, db에서 유저 정보를 한 번 조회해서 가져와야 합니다.
    user_sbti = current_user.sbti_code if hasattr(current_user, 'sbti_code') else "D-S-T" # 기본값 예시

    # 2. 백그라운드 태스크에 user_sbti 인자 추가
    background_tasks.add_task(
    service.parse_and_save_product, 
    db, 
    product_url, 
    current_user  # ✅ 여기서 3개만 넘김 (db, url, user)
)
    # 3. 유저에게는 분석 시작 알림과 설문지 전달
    return {
        "status": "ANALYSIS_STARTED",
        "survey_config": {
            "q1": "이거 장바구니/찜에 담은 지 얼마나 됐어?",
            "q2": "나한테 왜 연락한 거야?",
            "q3": "이 옷, 이미 거의 사기로 마음 정한 상태야? 아니면 아직 확신이 부족해?",
            "qc": "이 옷의 어떤 점이 네 마음을 뺏었어?"
        },
        "message": "분석 시작했어! 그전에 네 상태 좀 체크해보자."
    }


@router.post("/process-product")
async def process_product(url: str, user_sbti: str, db: Session = Depends(get_db)):
    # 1. 크롤링 수행 (가정: crawl_data 함수가 결과 dict를 반환)
    raw_data = await crawling_service.crawl_url(url)
    
    # 2. DB에 저장 (이때 ㅇㅇ핏 정보 등도 같이 저장)
    new_product = models.Product(**raw_data)
    db.add(new_product)
    db.commit()
    db.refresh(new_product) # 생성된 product_id를 가져옴
    
    # 3. "타고 타고" 분석 로직 실행
    # DB에 저장된 객체를 dict로 변환하여 분석기에 전달
    analysis_result = analyze_product_risk(raw_data, user_sbti) # 위험도 분석해 스코어 반환
    
    return {
        "message": "분석 완료!",
        "product_id": new_product.product_id,
        "analysis": analysis_result
    }


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

