import os
import pathlib
from fastapi import Path
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from pydantic_settings import BaseSettings, SettingsConfigDict   
from dotenv import load_dotenv

# 현재 파일 위치 기준으로 .env 파일 경로 찾기
# ✅ pathlib.Path로 이름을 명확하게 써줍니다.
env_path = pathlib.Path(__file__).parent.parent.parent / ".env"

# ✅ override=True를 써서 시스템 환경변수를 무조건 덮어씌웁니다.
load_dotenv(dotenv_path=env_path, override=True)


class Settings(BaseSettings):
    PROJECT_NAME: str = "또바바"
    
    # 1순위: 시스템 환경변수(또는 .env)에서 DATABASE_URL을 찾음
    # 2순위: 없으면 None (에러를 내서 알려주도록 설계)
    DATABASE_URL: str = os.getenv("DATABASE_URL")

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore"
    )
    
    SECRET_KEY: str = os.getenv("SECRET_KEY", "secret")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

settings = Settings()
