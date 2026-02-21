import os
import pathlib
from fastapi import Path
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from pydantic_settings import BaseSettings, SettingsConfigDict   
from dotenv import load_dotenv
import certifi

# 현재 파일 위치 기준으로 .env 파일 경로 찾기
# ✅ pathlib.Path로 이름을 명확하게 써줍니다.
env_path = pathlib.Path(__file__).parent.parent.parent / ".env"

# ✅ override=True를 써서 시스템 환경변수를 무조건 덮어씌웁니다.
load_dotenv(dotenv_path=env_path, override=True)


class Settings(BaseSettings):
    PROJECT_NAME: str = "또바바"
    ENV: str = os.getenv("APP_ENV", "local")
    DATABASE_URL: str = os.getenv("DATABASE_URL")
    # .env 파일의 변수명과 일치하게 선언해줍니다.
    # 이렇게 선언만 해두면 Pydantic이 .env에서 값을 자동으로 찾아 넣어줍니다.
    SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int

    @property
    def db_engine_kwargs(self):
        kwargs = {
            "pool_pre_ping": True,
            "pool_recycle": 3600,
            "connect_args": {}
        }
        
        # 1. 우선 가장 안전한 certifi 경로를 기본값으로 설정
        ca_path = certifi.where()
        
        # 2. 서버 환경용 경로 설정 (파일이 실제로 존재할 때만 교체)
        prod_ca_path = "/etc/ssl/certs/ca-certificates.crt"
        if os.path.exists(prod_ca_path):
            ca_path = prod_ca_path
            
        # 3. 최종 결정된 경로로 SSL 설정
        kwargs["connect_args"]["ssl"] = {"ca": ca_path}
        
        # 디버깅용: 현재 실제로 어떤 경로를 쓰는지 터미널에 찍어줍니다.
        print(f"DEBUG: 최종 SSL CA 경로 -> {ca_path}")
        
        return kwargs

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
