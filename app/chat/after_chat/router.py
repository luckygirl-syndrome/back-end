from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.users.router import get_current_user

from app.chat.after_chat import schemas
from app.chat.after_chat import service

router = APIRouter(prefix="/api/chat/after", tags=["After Chat"])


@router.post("/purchase", response_model=schemas.PurchaseStatusResponse)
def update_purchase(
    request: schemas.PurchaseStatusRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    사용자가 상품을 구매했는지 여부를 업데이트.
    """
    try:
        user_id = current_user["user_id"]
        return service.update_purchase_status(db, user_id, request)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        print("purchase status error:", e)
        raise HTTPException(
            status_code=500,
            detail="구매 여부 업데이트에 실패했습니다."
        )


@router.post("/feedback", response_model=schemas.FeedbackSubmitResponse)
def submit_feedback(
    request: schemas.FeedbackSubmitRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    자정 스케줄러를 통해 안내된 2주 후 피드백 받기.
    """
    try:
        user_id = current_user["user_id"]
        return service.submit_feedback(db, user_id, request)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        print("feedback error:", e)
        raise HTTPException(
            status_code=500,
            detail="피드백 저장에 실패했습니다."
        )
