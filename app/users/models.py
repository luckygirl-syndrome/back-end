from typing import Optional
from sqlalchemy import Column, Integer, String, Float, TEXT, BIGINT
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    # 언니가 원했던 최신 DB 구조
    user_id = Column(BIGINT, primary_key=True, index=True, autoincrement=True)
    nickname = Column(String(50))
    email = Column(String(255), unique=True, index=True)
    password = Column(String(100))  # hashed_password 대신 password
    persona_type = Column(TEXT, nullable=True) # persona 대신 persona_type
    profile_img = Column(TEXT, default="0") # profile_image_index 대신 profile_img
    
    # 드디어 추가된 쇼핑몰과 추구미!
    favorite_shops = Column(TEXT, nullable=True) # ["무신사", "지그재그"] 형태로 저장될 예정
    chu_gu_me = Column(String(30), nullable=True)

    # 🚩 [추가] 개인화 선호도 벡터 및 카운트
    # 12가지 피처의 평균값을 JSON 문자열로 저장
    mu_like = Column(TEXT, nullable=True)
    mu_regret = Column(TEXT, nullable=True)
    n_pos = Column(Integer, default=0)
    n_neg = Column(Integer, default=0)
