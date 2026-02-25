import os
import re
import json
from datetime import datetime
import sys
from dotenv import load_dotenv
import google.generativeai as genai

# 상위 디렉토리(Back-end)를 경로에 추가하여 app 모듈에 접근
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(current_dir)
if backend_dir not in sys.path:
    sys.path.append(backend_dir)

# blinker >= 1.9.0의 _saferef 삭제로 인한 seleniumwire 호환성 문제 우회 패치
import types
sys.modules['blinker._saferef'] = types.ModuleType('blinker._saferef')

# app 내부 파서 모듈 임포트
from app.products.parsers.item_parser import extract_features_from_url
from Final_Ttobaba import TobabaPromptBuilder, get_text, parse_llm_response

# .env 또는 AI.env 파일로부터 환경 변수 로드
# 현재 스크립트 파일이 위치한 디렉토리 기준
current_dir = os.path.dirname(os.path.abspath(__file__))
ai_env_path = os.path.join(current_dir, "AI.env")

if os.path.exists(ai_env_path):
    load_dotenv(ai_env_path)
else:
    load_dotenv()

# Gemini 설정
api_key = os.getenv("GOOGLE_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

class RiskCalculator:
    """Stage 2: 크롤링 + ML 결과 피처를 기반으로 충동 점수(impulse_score) 계산"""
    def compute_impulse_score(self, feature_dict: dict, user_context: dict) -> dict:
        score = 25 # 기본 점수
        reasons = []

        # 1. 높은 할인율 심리적 압박
        if feature_dict.get("discount_rate", 0) >= 30:
            score += 15
            reasons.append({
                "feature_key": "discount_rate",
                "value": feature_dict.get("discount_rate"),
                "guide": "할인율이 크면 ‘지금 사야 이득’처럼 느껴져서 마음이 빨리 기울 수 있어. 그래서 정가여도 살지 한 번만 생각해봐."
            })

        # 2. 트렌드 압박 (찜/좋아요 많음)
        if feature_dict.get("product_likes", 0) >= 5000:
            score += 15
            reasons.append({
                "feature_key": "product_likes",
                "value": feature_dict.get("product_likes"),
                "guide": "남들이 찜을 많이 눌렀다고 해서 너의 아이템들과 어울린다는 뜻은 아니잖아. 네가 이 옷을 구매했을 때 충분히 활용할 수 있는 아이템인지 생각해보자."
            })

        # 3. 리뷰 점수 기반 심리적 저항 감소
        if feature_dict.get("review_score", 0) >= 4.5:
            score += 10
            reasons.append({
                "feature_key": "review_score",
                "value": feature_dict.get("review_score"),
                "guide": "평점이 높다고 해서 무조건 좋은 상품이라는 뜻은 아니야. 네가 가장 중요하게 생각하는 요소에 대한 단점이 있지는 않은지 확인해보자."
            })

        # 4. ML 피처들
        if feature_dict.get("sim_trend_hype", 0) == 1:
            score += 20
            reasons.append({
                "feature_key": "sim_trend_hype",
                "value": 1,
                "guide": "마케팅이나 유행 키워드에 휩쓸려 충동적으로 결제하는 건 아닌지 돌아보자."
            })

        if feature_dict.get("sim_temptation", 0) == 1:
            score += 15
            reasons.append({
                "feature_key": "sim_temptation",
                "value": 1,
                "guide": "디자인이나 특징에 혹해서 평소 안 입는 스타일을 고르고 있는게 아닐까?"
            })

        if feature_dict.get("sim_bundle", 0) == 1:
            score += 10
            reasons.append({
                "feature_key": "sim_bundle",
                "value": 1,
                "guide": "묶음할인 때문에 굳이 필요없는 수량을 더 사려는 건 아닌지 체크해봐."
            })
            
        if feature_dict.get("is_direct_shipping", 0) == 1:
            score += 10
            reasons.append({
                "feature_key": "is_direct_shipping",
                "value": 1,
                "guide": "빨리 온다는 사실에 흥분해서 당장 필요하지 않은데 사고 있는 건 아닐까?"
            })

        return {
            "impulse_score": min(100, score),
            "impulse_reason_top2": reasons[:2] # 상위 2개 추출
        }

class PreferencePredictor:
    """Stage 3: 선호도 점수 계산 (personal, prior, total score)"""
    def compute_preference_score(self, feature_dict: dict, user_context: dict) -> dict:
        personal_score = 50
        prior_score = 50

        personal_reasons = []
        prior_reasons = []

        # Personal Score 계산 로직 (간단한 예시)
        target_style = user_context.get("target_style", "")
        frequent_malls = user_context.get("frequent_malls", [])
        
        # 1. 특정 쇼핑몰 사용여부에 따른 매칭 보너스
        if feature_dict.get("platform") in frequent_malls:
            personal_score += 20
            personal_reasons.append({
                "feature_key": "frequent_mall_match",
                "value": feature_dict.get("platform"),
                "guide": "네가 자주 쓰는 쇼핑몰에서 파는 옷이라 심리적으로 더 익숙하게 느끼고 있어."
            })
            
        # 2. 유저 페르소나 (SBTI / persona_type) 성향 매칭
        # 추가 기획에 맞춰 세부 SBTI 분기 처리가 가능합니다. (현재는 속성 유무로 가점)
        persona_type = user_context.get("persona_type")
        if persona_type:
            personal_score += 15
            personal_reasons.append({
                "feature_key": "persona_type",
                "value": persona_type,
                "guide": f"네 쇼핑 성향({persona_type})을 고려했을 때, 꽤 잘 어울리는 아이템일 확률이 높아."
            })

            
        # 리뷰/품질 점수 기반 Prior Score
        if feature_dict.get("review_score", 0) >= 4.7:
            prior_score += 15
            prior_reasons.append({
                "feature_key": "review_score",
                "value": feature_dict.get("review_score"),
                "guide": "다수의 사람들이 만족한 객관적인 리뷰가 있어서 실패 확률이 적다고 판단돼."
            })

        if feature_dict.get("sim_quality_logic", 0) == 1:
            prior_score += 15
            prior_reasons.append({
                "feature_key": "sim_quality_logic",
                "value": 1,
                "guide": "소재나 퀄리티 측면에서 긍정적인 평가가 많은 제품이야."
            })
            
        if feature_dict.get("sim_confidence", 0) == 1:
            prior_score += 10
            prior_reasons.append({
                "feature_key": "sim_confidence",
                "value": 1,
                "guide": "확신을 주는 키워드가 있어 꽤 괜찮은 선택이 될 수 있어."
            })

        total_score = (personal_score + prior_score) // 2
        preference_priority = "personal" if personal_score >= prior_score else "prior"

        return {
            "total_score": min(100, total_score),
            "mixing": {"preference_priority": preference_priority},
            "prior_score": min(100, prior_score),
            "prior_reason_top2": prior_reasons[:2],
            "personal_score": min(100, personal_score),
            "personal_reason_top2": personal_reasons[:2]
        }

class ModeDecider:
    """Stage 4: 위험도와 선호도를 기준으로 방어/결정 모드 채택"""
    def decide(self, impulse_score: int, preference_score: int, cart_duration: str) -> dict:
        mode = "BRAKE"
        level = 3
        label = "위험 (Danger)"
        goal = "강한 충동 흐름 차단"
        rationale = "높은 충동 리스크가 발견되어 구매 지연 권고"
        stance = "이성적이고 단호한 브레이크"
        tone = "객관적 사실 기반의 팩트 체크"
        strategy = "가장 큰 리스크를 지적하고 최소 24시간 보류 제안"

        if impulse_score >= 70:
            mode = "BRAKE"
            level = 3
        elif 50 <= impulse_score < 70:
            mode = "BRAKE"
            level = 2
            label = "신중 (Caution)"
            goal = "감정 환기 및 기준 재고정"
            rationale = "약간의 충동 흐름과 외부 요인 분리 필요"
            stance = "기준을 묻는 코치"
            tone = "부드럽지만 예리한 질문"
            strategy = "외부 조건 대신 본인의 핵심 기준 1개 재확인 유도"
        elif impulse_score < 50 and preference_score >= 60:
            mode = "DECIDER"
            level = 1
            label = "안전 (Safe)"
            goal = "결정 지지 및 확신 부여"
            rationale = "충동 낮고 선호/객관 지표 우수"
            stance = "유저 결정을 지지하는 조력자"
            tone = "편안하고 든든한 톤"
            strategy = "명확한 장점 요약 후 마지막 확인 후 결제 진행 지원"
        elif impulse_score < 50 and preference_score < 60:
            mode = "DECIDER"
            level = 2
            label = "주의 (Caution)"
            goal = "결정 단순화 및 대안 검토"
            rationale = "위험은 적으나 뚜렷한 매력이 확정되지 않음"
            stance = "우선순위를 정렬해주는 가이드"
            tone = "조언하는 친근한 톤"
            strategy = "우선순위 1개로 선택지를 좁혀주기"

        return {
            "mode": mode,
            "level": level,
            "label": label,
            "goal": goal,
            "rationale": rationale,
            "stance": stance,
            "tone": tone,
            "strategy": strategy
        }

class FinalScorePipeline:
    def __init__(self):
        # 모듈 내부에서 모델을 알아서 로드하므로 sim_model 생략
        self.risk_calc = RiskCalculator()
        self.pref_pred = PreferencePredictor()
        self.mode_decider = ModeDecider()

    def _build_llm_json(self, feature_dict, user_context, impulse_block, preference_block, mode_block, convo_block, current_step=1) -> dict:
        return {
            "meta": {
                "timestamp": datetime.now().isoformat()
            },
            "user_context": user_context,
            "product_context": {
                "name": feature_dict.get("name", "Unknown"),
                "brand": feature_dict.get("brand", "Unknown"),
                "mall": feature_dict.get("platform", "Unknown"),
                "price": feature_dict.get("할인 후 가격", 0) or feature_dict.get("discounted_price", 0),
                "category": feature_dict.get("category", "Unknown")
            },
            "impulse_block": impulse_block,
            "preference_block": preference_block,
            "mode_block": {"current_mode": mode_block["mode"]},
            "strategy_matrix": mode_block,
            "conversation_block": convo_block
        }

    def _run_llm(self, llm_data: dict, user_input: str, current_step: int, history: list):
        builder = TobabaPromptBuilder(
            json_data=llm_data,
            current_step=current_step,
            current_turn=len(history) + 1,
            user_input=user_input,
            history=history
        )

        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=builder.get_system_instruction(),
            generation_config={"temperature": 0.4, "top_p": 0.9}
        )

        full_prompt = builder.build_dynamic_context()
        try:
            response = model.generate_content(full_prompt)
            return get_text(response)
        except Exception as e:
            print(f"Gemini API Error: {e}")
            return ""

    def _compute_final_score(self, impulse_score: int, preference_score: int, attitude_code: str, mode: str) -> int:
        # 사용자가 요청한 충동구매 위험도(purchase pressure) 수식
        base = 0.6 * impulse_score + 0.4 * preference_score

        code_map = {"C1": -10, "N0": 0, "W1": 7, "W2": 15}
        base += code_map.get(attitude_code, 0)

        # W2는 모드 배율 적용 X (무조건 강하게)
        if attitude_code != "W2":
            if mode == "BRAKE":
                base *= 1.1
            elif mode == "DECIDER":
                base *= 0.9

        return max(0, min(100, round(base)))

    def run(self, url: str, user_profile: dict, conversation_block: dict, user_input: str = "이 제품 어때? 살까 말까?"):
        print(f"\n[1] Parsing URL features from {url}...")
        feature_dict = extract_features_from_url(url)
        
        print("\n[2] Computing Risk and Preference Scores...")
        impulse_block = self.risk_calc.compute_impulse_score(feature_dict, user_profile)
        preference_block = self.pref_pred.compute_preference_score(feature_dict, user_profile)
        
        print("\n[3] Deciding Mode & Strategy...")
        mode_block = self.mode_decider.decide(
            impulse_block["impulse_score"], 
            preference_block["total_score"], 
            conversation_block.get("cart_duration", "")
        )

        print(f" -> Chosen Mode: {mode_block['mode']} / Level: {mode_block['level']}")
        
        # Step 2(Final Output)를 강제로 돌리기 위해서 current_step=2 로 세팅
        STEP = 2
        llm_data = self._build_llm_json(
            feature_dict, user_profile, impulse_block, preference_block, mode_block, conversation_block, current_step=STEP
        )

        print("\n[4] Requesting LLM Orchestration...")
        llm_reply = self._run_llm(llm_data, "[EXIT] " + user_input, current_step=STEP, history=[])
        
        print("\n[5] Parsing LLM Response and Final Score...")
        clean_text, next_step, is_held, decision_code = parse_llm_response(llm_reply)

        if not decision_code:
            decision_code = "N0" # 기본값

        final_score = self._compute_final_score(
            impulse_block["impulse_score"], 
            preference_block["total_score"], 
            decision_code,
            mode_block["mode"]
        )

    def run_interactive(self, url: str, user_profile: dict, conversation_block: dict):
        print(f"\n[1] Parsing URL features from {url}...")
        feature_dict = extract_features_from_url(url)
        
        print("\n[2] Computing Risk and Preference Scores...")
        impulse_block = self.risk_calc.compute_impulse_score(feature_dict, user_profile)
        preference_block = self.pref_pred.compute_preference_score(feature_dict, user_profile)
        
        print("\n[3] Deciding Mode & Strategy...")
        mode_block = self.mode_decider.decide(
            impulse_block["impulse_score"], 
            preference_block["total_score"], 
            conversation_block.get("cart_duration", "")
        )

        print(f" -> Chosen Mode: {mode_block['mode']} / Level: {mode_block['level']}")
        
        print("\n[4] Starting Interactive Chat (Type [EXIT] or Natural End to get final score)...")
        current_step = 1
        history = []
        user_input = "이거 사고 싶어. 결정을 도와줘."
        
        while True:
            llm_data = self._build_llm_json(
                feature_dict, user_profile, impulse_block, preference_block, mode_block, conversation_block, current_step=current_step
            )

            print("\n또바바 생각중...")
            llm_reply = self._run_llm(llm_data, user_input, current_step=current_step, history=history)
            clean_text, next_step, is_held, decision_code = parse_llm_response(llm_reply)

            print(f"\n또바바: {clean_text}")

            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": clean_text})

            # Transition Logics
            if next_step == "EXIT" or decision_code or current_step == 2:
                if not decision_code: decision_code = "N0"
                print(f"\n[!] 대화 종료. (판정코드: {decision_code}) 최종 점수를 계산합니다.")
                break
                
            if next_step and next_step != current_step:
                current_step = next_step
                
            user_input = input("\n유저 입력: ")

        final_score = self._compute_final_score(
            impulse_block["impulse_score"], 
            preference_block["total_score"], 
            decision_code,
            mode_block["mode"]
        )

        return {
            "product_name": feature_dict.get("name", "Unknown"),
            "attitude_code": decision_code,
            "final_score": final_score, # 충동 구매 확률
            "impulse_score": impulse_block["impulse_score"],
            "preference_score": preference_block["total_score"],
            "mode": mode_block["mode"]
        }

if __name__ == "__main__":
    # Test execution
    test_url = "https://zigzag.kr/catalog/products/122935080"
    user_profile = {
        "persona_type": "DAT",
        "target_style": "페미닌 / 러블리",
        "frequent_malls": ["ZIGZAG", "MUSINSA"]
    }
    conversation_block = {
        "cart_duration": "1일 전",
        "contact_reason": "가격이 싸서 눈길이 감",
        "purchase_certainty": "반반",
        "key_appeal": "할인과 무료배송"
    }

    pipeline = FinalScorePipeline()
    # 단판 호출(run) 대신 대화형 시뮬레이션(run_interactive) 실행
    result = pipeline.run_interactive(test_url, user_profile, conversation_block)
    
    print("\n" + "="*50)
    print("? [FINAL OUTPUT (충동구매 확률)] ?")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("="*50)