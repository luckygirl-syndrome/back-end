from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from app.products.models import UserProduct
from app.chat.after_chat import schemas

def update_purchase_status(db: Session, user_id: int, req: schemas.PurchaseStatusRequest) -> schemas.PurchaseStatusResponse:
    """사용자가 실제로 구매했는지 여부 기록하기"""
    up = db.query(UserProduct).filter(
        UserProduct.user_id == user_id,
        UserProduct.user_product_id == req.user_product_id
    ).first()

    if not up:
        raise ValueError("해당 상품을 찾을 수 없습니다.")

    # 구매 상태 업데이트
    up.is_purchased = 1 if req.is_purchased else 0
    # 필요한 경우 완료 시간을 기록
    if not up.completed_at:
        up.completed_at = datetime.now()

    db.commit()

    return schemas.PurchaseStatusResponse(
        status="success",
        message="구매 여부가 성공적으로 업데이트 되었습니다."
    )

def submit_feedback(db: Session, user_id: int, req: schemas.FeedbackSubmitRequest) -> schemas.FeedbackSubmitResponse:
    """2주 후 피드백 받아서 저장하기"""
    up = db.query(UserProduct).filter(
        UserProduct.user_id == user_id,
        UserProduct.user_product_id == req.user_product_id
    ).first()

    if not up:
        raise ValueError("해당 상품을 찾을 수 없습니다.")

    # 실제 피드백 데이터를 DB에 저장
    if req.feedback_text is not None:
        up.feedback_text = req.feedback_text
    if req.rating is not None:
        up.feedback_rating = req.rating
        
    db.commit()

    return schemas.FeedbackSubmitResponse(
        status="success",
        message="피드백이 성공적으로 저장되었습니다."
    )


# -------------------------------------------------------------------
# [Scheduler] 하루 한 번 자정 12시 실행 (프레임워크 종속적 로직)
# -------------------------------------------------------------------
# FastAPI 환경에서 매일 자정에 실행하려면 보통 `APScheduler`를 사용합니다.
# 
# 1. 설치: pip install apscheduler
# 2. main.py 혹은 lifespan에 스케줄러 등록
#
# async def daily_midnight_task():
#     # 1) Session 열기
#     db = next(get_db())
#     
#     # 2) "상담을 마친지 2주" 된 유저 찾기 (예시)
#     two_weeks_ago = datetime.now() - timedelta(days=14)
#     target_users = db.query(UserProduct).filter(
#         UserProduct.completed_at <= two_weeks_ago,
#         UserProduct.is_purchased == None # 등등의 조건
#     ).all()
#     
#     # 3) 프론트엔드로 전달 (FCM 푸시, MQ 발송 등)
#     for user in target_users:
#         send_push_notification(user.user_id, "2주 전에 고민했던 상품, 어떻게 하셨나요?")
# 
# # 4) [APScheduler 설정 예시]
# # from apscheduler.schedulers.asyncio import AsyncIOScheduler
# # scheduler = AsyncIOScheduler()
# # scheduler.add_job(daily_midnight_task, 'cron', hour=0, minute=0)
# # scheduler.start()
