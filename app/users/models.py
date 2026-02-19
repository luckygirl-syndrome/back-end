from typing import Optional
from sqlalchemy import Column, Integer, String, Float, Text
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True)
    hashed_password = Column(String(255))
    name = Column(String(255))
    
    # 이미지 파일 주소 대신 캐릭터 번호(0, 1, 2...)를 저장합니다.
    profile_image_index = Column(Integer, default=0) 
    persona = Column(Text, nullable=True)
