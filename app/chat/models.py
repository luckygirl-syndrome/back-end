from sqlalchemy import Column, Integer, DateTime, BigInteger
from app.core.database import Base

class Chat(Base):
    __tablename__ = "chat"

    chat_id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger)
    created_at = Column(DateTime)

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