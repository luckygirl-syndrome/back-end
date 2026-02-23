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
    
    user_input = "설문 완료!"
    # 3. 챗봇 답변 생성 시작
    # 서비스 레이어에서 이제 언니가 원했던 그 '최종 JSON' 형식을 만들어서 Gemini를 호출함
    first_response = await service.get_chat_response(
        db=db, 
        user_id=current_user.user_id, 
        user_product_id=user_product_id, 
        user_answers=user_answers, 
        user_input=user_input # 첫 진입이므로 고정 메시지 전달
    )

    # 4. ✅ 유저의 설문 질문과 답변을 쌍으로 묶어서 사용자/AI 메시지로 저장
    survey_pairs = [
        ("이거 장바구니/찜에 담은 지 얼마나 됐어?", service.get_q1_text(user_answers.get('q1'))),
        ("나한테 왜 연락한 거야?", service.get_q2_text(user_answers.get('q2'))),
        ("이 옷, 이미 거의 사기로 마음 정한 상태야? 아니면 아직 확신이 부족해?", service.get_q3_text(user_answers.get('q3'))),
        ("이 옷의 어떤 점이 네 마음을 뺏었어?", service.get_qc_text(user_answers.get('qc')))
    ]

    for question, answer in survey_pairs:
        # 질문 저장 (assistant)
        service.save_chat_message(
            db=db,
            user_id=current_user.user_id,
            user_product_id=user_product_id,
            role="assistant",
            content=question
        )
        # 답변 저장 (user)
        service.save_chat_message(
            db=db,
            user_id=current_user.user_id,
            user_product_id=user_product_id,
            role="user",
            content=answer
        )

    # 5. ✅ AI의 첫 분석 답변 저장
    service.save_chat_message(
        db=db,
        user_id=current_user.user_id,
        user_product_id=user_product_id,
        role="assistant",
        content=first_response
    )
    
    return {"reply": first_response}

@router.get(
    "/list", 
    response_model=ChatListResponse,
    summary="유저의 채팅 목록 조회 (상품별 중복 제거)",
    description="""
    현재 유저가 대화 중인 모든 채팅방 목록을 반환합니다.
    동일한 상품을 여러 번 분석한 경우, 가장 최근에 생성된 채팅방 하나만 리스트에 포함됩니다.
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