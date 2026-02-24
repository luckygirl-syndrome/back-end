from sqlalchemy import Column, String, DateTime, Integer, Float, Text, TIMESTAMP
from sqlalchemy.dialects.mysql import BIGINT, TINYINT # ✅ MySQL 전용 타입은 여기서!
from sqlalchemy.ext.declarative import declarative_base
import datetime

# 만약 이미 공통 Base가 있다면 그걸 쓰시고, 없다면 여기서 정의합니다.
from app.core.database import Base

class Product(Base):
    __tablename__ = "products"

    product_img = Column(Text)       # 상품 메인 이미지
    product_id = Column(BIGINT, primary_key=True, index=True)
    product_name = Column(String(255))
    category = Column(String(50))
    price = Column(Integer)
    discount_rate = Column(Float)
    is_direct_shipping = Column(TINYINT(1))
    free_shipping = Column(TINYINT(1))
    review_count = Column(Integer)
    review_score = Column(Float)
    product_likes = Column(String(255))
    platform = Column(String(50))
    product_img = Column(Text)
    
    # ✅ AI 분석용 심리 축 6개
    sim_temptation = Column(TINYINT(1))
    sim_trend_hype = Column(TINYINT(1))
    sim_fit_anxiety = Column(TINYINT(1))
    sim_quality_logic = Column(TINYINT(1))
    sim_bundle = Column(TINYINT(1))
    sim_confidence = Column(TINYINT(1))
    
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

class UserProduct(Base):
    __tablename__ = "user_product"

    user_product_id = Column(BIGINT, primary_key=True, index=True, autoincrement=True)
    user_id = Column(BIGINT, nullable=False)
    product_id = Column(BIGINT, nullable=False)
    requested_at = Column(DateTime, default=datetime.datetime.now)
    completed_at = Column(DateTime)
    duration_ms = Column(Integer)
    status = Column(String(50))
    user_type = Column(String(50))
    impulse_score = Column(Integer)
    risk_score_2 = Column(Integer)
    preference_score = Column(Integer, default=50)
    is_purchased = Column(TINYINT(1))
    prompt_data = Column(Text)  # ✅ 챗봇에게 넘길 최종 완전체 JSON 캐싱
    # ✅ 2주 후 피드백 결과 저장용 컬럼
    feedback_text = Column(Text)
    feedback_rating = Column(Integer)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)