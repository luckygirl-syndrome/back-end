from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from app.core.database import get_db
from app.users.router import get_current_user

from app.chat.models import Chat
from app.users.models import User
from app.products.models import UserProduct   # user_product 사용

router = APIRouter(prefix="/api/dashboard", tags=["Home"])


@router.get("/home")
def get_home_dashboard(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    홈 화면 대시보드 데이터 조회
    """

    try:
        user_id = current_user["user_id"]

        # -------------------------
        # 1. 사용자 이름
        # -------------------------
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="유저 없음")

        user_name = user.name

        # -------------------------
        # 2. 절약 횟수 (is_purchased = 0)
        # -------------------------
        saved_count = (
            db.query(UserProduct)
            .filter(
                UserProduct.user_id == user_id,
                UserProduct.is_purchased == 0
            )
            .count()
        )

        # -------------------------
        # 3. 최근 3개월 대화 수
        # -------------------------
        three_months_ago = datetime.now() - timedelta(days=90)

        recent_chat_count = (
            db.query(Chat)
            .filter(
                Chat.user_id == user_id,
                Chat.created_at >= three_months_ago
            )
            .count()
        )

        # -------------------------
        # 4. 전체 대화 수
        # -------------------------
        total_chat_count = (
            db.query(Chat)
            .filter(Chat.user_id == user_id)
            .count()
        )

        return {
            "status": "success",
            "data": {
                "user_name": user_name,
                "saved_count": saved_count,
                "recent_chat_count": recent_chat_count,
                "total_chat_count": total_chat_count
            }
        }

    except Exception as e:
        print("dashboard error:", e)
        raise HTTPException(
            status_code=500,
            detail="홈 데이터를 불러오지 못했어."
        )