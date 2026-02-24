"""
app/chat/agent.py

Gemini LLM 연동 전담 모듈.
- 모델 캐싱: MD5 해시 기반 GenerativeModel 인스턴스 관리
- system_instruction 전역 캐시 (L1 — RAM)
- 프롬프트 조립 + 생성 + 파싱 통합
"""
import hashlib
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import google.generativeai as genai

from .prompt import TobabaPromptBuilder

# ──────────────────────────────────────────────
# 전역 캐시 (L1 — 서버 메모리)
# ──────────────────────────────────────────────
_SYSTEM_INSTRUCTION: Optional[str] = None   # lifespan에서 1회 빌드
_MODEL_CACHE: Dict[str, Any] = {}           # hash_key → GenerativeModel

# 기본 Generation Config
DEFAULT_GEN_CONFIG = {
    "temperature": 0.4,
    "top_p": 0.9,
}

DEFAULT_MODEL_NAME = "gemini-2.5-flash"


# ──────────────────────────────────────────────
# 초기화 (lifespan에서 호출)
# ──────────────────────────────────────────────
def init_agent() -> None:
    """
    서버 시작 시 1회 호출.
    - Gemini API 키 설정
    - system_instruction 전역 캐시에 저장
    """
    global _SYSTEM_INSTRUCTION

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY가 설정되지 않았습니다. .env 파일을 확인해주세요.")
    genai.configure(api_key=api_key)

    # 빈 데이터로 빌더를 만들어 정적 규칙(system_instruction)만 추출
    dummy_builder = TobabaPromptBuilder(json_data={})
    _SYSTEM_INSTRUCTION = dummy_builder.get_system_instruction()

    print(f"✅ [agent] system_instruction 캐시 완료 (길이: {len(_SYSTEM_INSTRUCTION)}자)")
    print(f"✅ [agent] Gemini API 설정 완료")


def get_system_instruction() -> str:
    """캐시된 system_instruction 반환."""
    if _SYSTEM_INSTRUCTION is None:
        raise RuntimeError("agent.init_agent()가 호출되지 않았습니다.")
    return _SYSTEM_INSTRUCTION


# ──────────────────────────────────────────────
# 모델 캐싱
# ──────────────────────────────────────────────
def _make_cache_key(model_name: str, system_instruction: str) -> str:
    """model_name + system_instruction 해시로 캐시 키 생성."""
    si_hash = hashlib.md5(system_instruction.encode("utf-8")).hexdigest()[:12]
    return f"model:{model_name}:{si_hash}"


def _get_or_create_model(
    model_name: str = DEFAULT_MODEL_NAME,
    system_instruction: Optional[str] = None,
) -> Any:
    """캐시된 GenerativeModel 반환. 없으면 생성 후 캐시."""
    si = system_instruction or get_system_instruction()
    cache_key = _make_cache_key(model_name, si)

    if cache_key not in _MODEL_CACHE:
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=si,
            generation_config=DEFAULT_GEN_CONFIG,
        )
        _MODEL_CACHE[cache_key] = model
        print(f"🔧 [agent] 모델 생성 및 캐시: {cache_key}")
    return _MODEL_CACHE[cache_key]


# ──────────────────────────────────────────────
# LLM 응답 파싱
# ──────────────────────────────────────────────
def parse_llm_response(response: str) -> Tuple[str, Optional[Any], bool, Optional[str]]:
    """
    LLM 응답 텍스트를 파싱하여 (clean_text, next_step, is_held, decision_code) 반환.
    - next_step: 2 | "EXIT" | None
    - is_held: Step 유지 여부
    - decision_code: "C1" | "N0" | "W1" | "W2" | None
    """
    if response is None:
        response = ""
    response = str(response)

    next_step = None
    is_held = False

    if "[EXIT]" in response:
        next_step = "EXIT"

    if "[STEP_MOVED:2]" in response:
        next_step = 2

    # CODE 블록 파싱
    decision_code = None
    code_match = re.search(r"\[CODE:(.*?)\]", response)
    if code_match:
        decision_code = code_match.group(1).strip()

    held_match = re.search(r"\[STEP_HELD(?::\d+)?\]", response)
    if held_match and next_step is None:
        is_held = True

    # 시스템 태그 제거
    clean_text = response
    clean_text = clean_text.replace("[STEP_MOVED:2]", "").replace("[STEP_MOVED:3]", "").replace("[EXIT]", "")
    clean_text = re.sub(r"\[CODE:.*?\]", "", clean_text)
    clean_text = re.sub(r"\[STEP_HELD(?::\d+)?\]", "", clean_text)
    clean_text = clean_text.strip()

    return clean_text, next_step, is_held, decision_code


# ──────────────────────────────────────────────
# 핵심: 프롬프트 조립 + Gemini 호출
# ──────────────────────────────────────────────
async def generate_response(
    json_data: dict,
    current_step: int,
    current_turn: int,
    user_input: str,
    history: List[Dict[str, Any]],
) -> Tuple[str, Optional[Any], bool, Optional[str]]:
    """
    프롬프트를 조립하고 Gemini를 호출하여 파싱된 결과를 반환.

    Returns: (clean_text, next_step, is_held, decision_code)
    """
    builder = TobabaPromptBuilder(
        json_data=json_data,
        current_step=current_step,
        current_turn=current_turn,
        user_input=user_input,
        history=history,
    )

    # 매 턴마다 동적 규칙이 바뀌므로 모델을 system_instruction 기준으로 캐시
    model = _get_or_create_model()

    # 매 턴 고정된 프롬프트와 동적 프롬프트 결합
    full_prompt = builder.get_fixed_context() + "\n\n" + builder.get_dynamic_context()

    try:
        response = model.generate_content(full_prompt)
        raw_text = _get_text(response)
    except Exception as e:
        print(f"❌ [agent] Gemini API 에러: {e}")
        return "미안, 내 뇌에 잠깐 렉 걸렸어. 다시 말해줄래?", None, False, None

    if not raw_text:
        raw_text = f"{user_input}라고 했지. 그럼 이 옷이 대체 불가한 포인트가 딱 하나만 뭐야?"

    # 파싱
    clean_text, next_step, is_held, decision_code = parse_llm_response(raw_text)

    # 안전장치: 첫 턴에 바로 EXIT/Step2 방지
    if current_turn == 1 and next_step in (2, "EXIT"):
        next_step = None
        is_held = True

    # 안전장치: Step1에서 유저 응답 2개 미만이면 Step2 이동 방지
    if current_step == 1 and next_step == 2:
        user_msgs = [m for m in history if m.get("role") == "user"]
        if len(user_msgs) < 2:
            next_step = None
            is_held = True

    return clean_text, next_step, is_held, decision_code


def _get_text(resp) -> str:
    """Gemini 응답 객체에서 텍스트 추출."""
    try:
        chunks = []
        for cand in resp.candidates:
            for part in cand.content.parts:
                if getattr(part, "text", None):
                    chunks.append(part.text)
        return "".join(chunks).strip()
    except Exception:
        return (getattr(resp, "text", "") or "").strip()
