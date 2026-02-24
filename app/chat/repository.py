"""
app/chat/repository.py

Redis CRUD 전담 모듈 (비동기 전용).
- chat:{chat_id}:item_json   → 상품 분석 JSON
- chat:{chat_id}:ctx_fixed:v1 → 고정 프롬프트 텍스트
- chat:{chat_id}:history       → 대화 기록 (List)
"""
import json
from typing import Any, Dict, List, Optional, Tuple

import redis.asyncio as aioredis

from app.core.config import settings

# ──────────────────────────────────────────────
# Connection Pool (lifespan에서 init/close)
# ──────────────────────────────────────────────
_pool: Optional[aioredis.Redis] = None

CTX_VERSION = "v1"
DEFAULT_TTL = 60 * 60 * 24   # 24시간
HISTORY_MAX_LEN = 40          # 최근 40개 메시지만 유지


async def init_redis_pool() -> None:
    """서버 시작 시 Connection Pool 생성."""
    global _pool
    _pool = aioredis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=0,
        decode_responses=True,
    )
    await _pool.ping()
    print("✅ [repository] 비동기 Redis pool 연결 완료")


async def close_redis_pool() -> None:
    """서버 종료 시 Connection Pool 해제."""
    global _pool
    if _pool:
        await _pool.aclose()
        _pool = None
        print("🔌 [repository] Redis pool 해제 완료")


def _get_pool() -> aioredis.Redis:
    if _pool is None:
        raise RuntimeError("Redis pool이 초기화되지 않았습니다. lifespan 확인 요망.")
    return _pool


# ──────────────────────────────────────────────
# Key 헬퍼
# ──────────────────────────────────────────────
def _key_item_json(chat_id: int) -> str:
    return f"chat:{chat_id}:item_json"


def _key_ctx_fixed(chat_id: int) -> str:
    return f"chat:{chat_id}:ctx_fixed:{CTX_VERSION}"


def _key_history(chat_id: int) -> str:
    return f"chat:{chat_id}:history"


# ──────────────────────────────────────────────
# 세션 데이터 CRUD
# ──────────────────────────────────────────────
async def save_item_json(chat_id: int, data: dict) -> None:
    """상품 분석 JSON 저장 (TTL 24h)."""
    r = _get_pool()
    await r.setex(
        _key_item_json(chat_id),
        DEFAULT_TTL,
        json.dumps(data, ensure_ascii=False),
    )


async def save_ctx_fixed(chat_id: int, data: dict) -> None:
    """고정 프롬프트 컨텍스트 저장 (TTL 24h)."""
    r = _get_pool()
    await r.setex(
        _key_ctx_fixed(chat_id),
        DEFAULT_TTL,
        json.dumps(data, ensure_ascii=False),
    )


async def get_session_data(chat_id: int) -> Tuple[Optional[dict], Optional[dict]]:
    """
    MGET으로 item_json + ctx_fixed를 한 번에 조회.
    Returns: (item_json_dict | None, ctx_fixed_dict | None)
    """
    r = _get_pool()
    raw_item, raw_ctx = await r.mget(
        _key_item_json(chat_id),
        _key_ctx_fixed(chat_id),
    )
    item_json = json.loads(raw_item) if raw_item else None
    ctx_fixed = json.loads(raw_ctx) if raw_ctx else None
    return item_json, ctx_fixed


# ──────────────────────────────────────────────
# 히스토리 CRUD
# ──────────────────────────────────────────────
async def push_history(chat_id: int, role: str, content: str) -> None:
    """대화 메시지 1개를 히스토리에 추가 + LTRIM으로 길이 제한."""
    r = _get_pool()
    entry = json.dumps({"role": role, "content": content}, ensure_ascii=False)
    await r.rpush(_key_history(chat_id), entry)
    await r.ltrim(_key_history(chat_id), -HISTORY_MAX_LEN, -1)
    # TTL 갱신
    await r.expire(_key_history(chat_id), DEFAULT_TTL)


async def get_history(chat_id: int) -> List[Dict[str, Any]]:
    """히스토리 전체 조회 → list of dict."""
    r = _get_pool()
    raw_list = await r.lrange(_key_history(chat_id), 0, -1)
    return [json.loads(item) for item in raw_list]
