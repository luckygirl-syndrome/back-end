import os

# SSL context is handled by the connection string parameters in Config for pymysql
# But for TiDB Cloud, ensuring SSL is recommended.
# Note: The path /etc/ssl/cert.pem is standard on some Linux distros. 
# On Mac/Windows or if using a specific CA bundle provided by TiDB, adjust accordingly.
# For simplicity, we might default to standard system CA bundle or allow insecure for dev if explicitly requested (not recommended).

# app/core/database.py
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from .config import settings

if not settings.DATABASE_URL:
    raise ValueError("DATABASE_URL이 설정되지 않았습니다. .env 파일을 확인해주세요.")

print("="*50)
print(f"DEBUG: 현재 SQLAlchemy에 전달되는 주소 -> [{settings.DATABASE_URL[:30]}...]")
print("="*50)

# SSL 설정을 추가한 엔진 생성
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    connect_args={
        "ssl": {"ca": "/etc/ssl/certs/ca-certificates.crt"} # 서버(Ubuntu) 환경의 SSL 인증서 경로
    }
)

# 2. 세션 설정
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 3. Base 선언 (이게 없어서 에러가 난 거예요!)
Base = declarative_base() 

# 4. DB 세션 획득용 함수
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# DEBUG용 출력
print("="*50)
print(f"DEBUG: 현재 SQLAlchemy에 전달되는 주소 -> [{settings.DATABASE_URL[:30]}...]")
print("="*50)