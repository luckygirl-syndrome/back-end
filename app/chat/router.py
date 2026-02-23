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
from app.chat.schemas import ChatListResponse
from app.chat import schemas
from app.chat.models import Chat

router = APIRouter(prefix="/api/chat", tags=["chat"])

@router.post(
    "/start",
    summary="채팅 세션 시작 및 설문 항목 전달",
    description="""
    유저가 보낸 상품 URL을 분석하기 위해 임시 분석 레코드(UserProduct)를 생성하고,
    백그라운드에서 크롤링 및 상품 분석을 시작합니다.
    분석이 진행되는 동안 유저가 답변해야 할 심리 설문(Survey) 항목들을 반환합니다.
    """
)
async def start_chat(
    product_url: str, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # ✅ 토큰으로 유저 식별
):
    # 1. 페르소나 정리
    user_persona_code = service.clean_persona_code(current_user)

    # 2. 임시 UserProduct 레코드 생성 (비즈니스 로직은 서비스로 이동)
    user_prod = service.create_initial_user_product(db, current_user.user_id, user_persona_code)

    # 3. 백그라운드 태스크에 user_product_id 전달
    background_tasks.add_task(
        service.parse_and_save_product, 
        db, 
        product_url, 
        current_user,
        user_prod.user_product_id
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
from app.chat.schemas import SurveyRequest 
from app.chat import service

@router.post(
    "/finalize-survey/{user_product_id}",
    summary="설문 답변 제출 및 챗봇 첫 응답 생성",
    description="""
    유저의 설문 답변을 기반으로 챗봇의 첫 번째 분석 메시지를 생성합니다.
    이 과정에서 챗봇의 설문 질문들과 유저의 답변들을 채팅 내용(Chat)으로 변환하여 저장하며,
    Redis와 DB에 대화 내역을 동기화합니다.
    """
)
async def finalize_survey(
    user_product_id: int,
    request: SurveyRequest, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    # 1. Pydantic 모델을 dict로 변환 (q1, q2, q3, qc 포함)
    user_answers = request.model_dump()

    # 2. 이 유저가 요청한 특정 상품 분석 기록 찾기
    user_prod = db.query(UserProduct).filter(
        UserProduct.user_product_id == user_product_id,
        UserProduct.user_id == current_user.user_id
    ).first()

    if not user_prod:
        raise HTTPException(status_code=404, detail="요청한 상품 기록이 없어요!")

    user_input = "설문 완료!"
    # 3. 챗봇 답변 생성 시작
    first_response = await service.get_chat_response(
        db=db, 
        user_id=current_user.user_id, 
        user_product_id=user_product_id, 
        user_answers=user_answers, 
        user_input=user_input
    )

    # 4. 설문 내역 및 AI 첫 응답 저장 (비즈니스 로직은 서비스로 이동)
    service.finalize_chat_survey(
        db=db,
        user_id=current_user.user_id,
        user_product_id=user_product_id,
        user_answers=user_answers,
        first_response=first_response
    )
    
    return {"reply": first_response}

@router.get(
    "/list", 
    response_model=ChatListResponse,
    summary="유저의 채팅 목록 조회",
    description="""
    현재 유저가 대화 중인 모든 채팅방 목록을 반환합니다.
    최신 대화순으로 정렬되어 제공됩니다.
    """
)
async def get_chat_list(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return service.get_user_chat_list(db, current_user.user_id)

@router.get(
    "/room/{user_product_id}", 
    response_model=schemas.ChatRoomDetailResponse,
    summary="특정 채팅방 상세 정보 및 메시지 목록 조회",
    description="""
    특정 채팅방의 상단 상품 정보와 지금까지 나눈 전체 대화 내역을 조회합니다.
    속도 향상을 위해 Redis 캐시를 우선적으로 확인하며, 캐시가 없을 경우 DB에서 복구합니다.
    """
)
async def get_chat_room_detail(
    user_product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    특정 채팅방(상품 대화)의 상세 정보와 메세지 목록을 조회합니다.
    """
    # 서비스 레이어 호출
    detail = service.get_chat_messages(db, user_product_id, current_user.user_id)
    
    if not detail:
        raise HTTPException(status_code=404, detail="채팅방 정보를 찾을 수 없어요.")
        
    return detail

@router.post(
    "/exit/{user_product_id}",
    summary="채팅방 종료",
    description="""
    해당 채팅방의 상태를 'FINISHED'(대화 종료)로 변경합니다.
    채팅방 목록에서 해당 상품의 상태를 업데이트하는 데 사용됩니다.
    """
)
async def exit_chat(
    user_product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    채팅을 종료 상태(FINISHED)로 변경합니다.
    """
    success = service.finish_chat(db, user_product_id, current_user.user_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="요청한 채팅 방을 찾을 수 없어요.")
        
    return {"status": "SUCCESS", "message": "채팅이 종료되었습니다."}