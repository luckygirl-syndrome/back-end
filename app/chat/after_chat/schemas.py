from pydantic import BaseModel
from typing import Optional

# -------------------------------------------------------------------
# 1. 구매 여부 확인 API (Purchase Status)
# -------------------------------------------------------------------
class PurchaseStatusRequest(BaseModel):
    user_product_id: int
    is_purchased: bool # True: 구매함, False: 안 샀음
<<<<<<< HEAD
=======
    is_abandoned: bool = False  # 구매 포기 여부 추가
>>>>>>> main

class PurchaseStatusResponse(BaseModel):
    status: str
    message: str

# -------------------------------------------------------------------
# 2. 2주 후 피드백 답변 API (Feedback)
# -------------------------------------------------------------------
class FeedbackSubmitRequest(BaseModel):
    user_product_id: int
    # 예: 피드백 텍스트, 별점 등 필요한 필드 추가 가능
    feedback_text: Optional[str] = None
    rating: Optional[int] = None

class FeedbackSubmitResponse(BaseModel):
    status: str
    message: str
