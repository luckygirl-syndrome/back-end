from sqlalchemy import Column, Integer, DateTime, BigInteger
from app.core.database import Base

class Chat(Base):
    __tablename__ = "chat"

    chat_id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger)
    created_at = Column(DateTime)