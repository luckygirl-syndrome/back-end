import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from .config import settings

# 1. DATABASE_URL 체크
if not settings.DATABASE_URL:
    raise ValueError("DATABASE_URL이 설정되지 않았습니다. .env 파일을 확인해주세요.")

# DEBUG용 출력
print("="*50)
print(f"DEBUG: 현재 SQLAlchemy에 전달되는 주소 -> [{settings.DATABASE_URL[:30]}...]")
print("="*50)

# settings에서 알아서 환경에 맞는 kwargs를 뱉어줍니다.
engine = create_engine(
    settings.DATABASE_URL, 
    **settings.db_engine_kwargs
)

# 3. 세션 설정
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 4. Base 선언 (모델들이 상속받을 기본 클래스)
Base = declarative_base() 

# 5. DB 세션 획득용 함수
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()