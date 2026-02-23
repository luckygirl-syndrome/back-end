from pydantic import BaseModel, Field

class SurveyRequest(BaseModel):
    q1: int = Field(..., description="장바구니 기간 (1-5)", example=1)
    q2: int = Field(..., description="연락 이유 (1-4)", example=3)
    q3: int = Field(..., description="구매 확신도 (1-4)", example=2)
    qc: int = Field(..., description="핵심 매력 (1-7)", example=6)

from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class ChatListItem(BaseModel):
    user_product_id: int
    product_name: str
    product_img: Optional[str]
    price: int
    last_chat_time: str  # "오늘", "어제" 등으로 변환해서 줄 거야
    status_label: str    # "구매 완료", "구매 포기", "고민 중"
    is_purchased: Optional[int]

class ChatListResponse(BaseModel):
    latest_chat: Optional[ChatListItem]
    all_chats: List[ChatListItem]

class ChatMessageResponse(BaseModel):
    role: str       # "user" 또는 "assistant"
    content: str    # 대화 내용
    created_at: datetime

class ChatRoomDetailResponse(BaseModel):
    user_product_id: int
    product_name: str
    product_img: Optional[str]
    price: int
    status_label: str
    messages: List[ChatMessageResponse]

    class Config:
        from_attributes = True