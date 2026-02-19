import os, json, re, time
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from transformers import AutoTokenizer, AutoModel

# --- 1. 유틸리티 및 모델 구조 (추가 필수) ---
def mean_pool(last_hidden_state, attention_mask):
    mask = attention_mask.unsqueeze(-1).type_as(last_hidden_state)
    summed = (last_hidden_state * mask).sum(dim=1)
    counts = mask.sum(dim=1).clamp(min=1e-9)
    return summed / counts

def load_runtime_config(model_dir: str):
    cfg_path = os.path.join(model_dir, "config_runtime.json")
    if not os.path.exists(cfg_path):
        raise FileNotFoundError(f"config_runtime.json 없음: {cfg_path}")
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)

def apply_rules(text: str, AXES, RULES):
    t = str(text).lower()
    scores = np.zeros(len(AXES), dtype=np.float32)
    for j, ax in enumerate(AXES):
        for kw in RULES.get(ax, []):
            if str(kw).lower() in t:
                scores[j] = 1.0
                break
    return scores

class StudentDistillModel(nn.Module):
    def __init__(self, encoder, hidden_size, out_dim=6, dropout=0.1):
        super().__init__()
        self.encoder = encoder
        self.dropout = nn.Dropout(dropout)
        self.head = nn.Linear(hidden_size, out_dim)

    def forward(self, input_ids, attention_mask):
        out = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        pooled = mean_pool(out.last_hidden_state, attention_mask)
        pooled = F.normalize(pooled, p=2, dim=-1)
        pooled = self.dropout(pooled)
        return self.head(pooled)
    
# --- 4. 모델 로더 (Mac 로컬 최적화 버전) ---
class KeywordAxisInfer:
    def __init__(self, model_dir: str, device: str | None = None):
        self.model_dir = model_dir
        self.cfg = load_runtime_config(model_dir)

        self.AXES = self.cfg["AXES"]
        self.THRESHOLDS = self.cfg["THRESHOLDS"]
        self.RULES = self.cfg["RULES"]
        self.rule_weight = float(self.cfg.get("rule_weight", 1.2))
        self.max_len = int(self.cfg.get("max_len", 128))

        # ✅ Mac(M1/M2/M3)을 위해 mps 우선 순위 부여
        if device is None:
            if torch.backends.mps.is_available():
                device = "mps"
            elif torch.cuda.is_available():
                device = "cuda"
            else:
                device = "cpu"
        self.device = torch.device(device)
        print(f"DEBUG: 현재 장치 -> {self.device}")

        # ✅ 1. Tokenizer 로드 (model_dir 폴더 안의 파일들 사용)
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        
        # ✅ 2. Encoder 로드 (E5 모델 등)
        self.encoder = AutoModel.from_pretrained(self.cfg["STUDENT_NAME"]).to(self.device)

        # ✅ 3. Student Head 구조 정의 및 가중치 로드
        hidden = self.encoder.config.hidden_size
        self.student = StudentDistillModel(self.encoder, hidden_size=hidden, out_dim=len(self.AXES)).to(self.device)

        head_path = os.path.join(model_dir, "student_head.pt")
        if not os.path.exists(head_path):
            raise FileNotFoundError(f"student_head.pt 없음! 드라이브에서 받았는지 확인해줘: {head_path}")

        # weights_only=True는 최신 PyTorch 보안 권장사항이야
        state = torch.load(head_path, map_location=self.device)
        self.student.load_state_dict(state, strict=True)
        self.student.eval()
        print("✅ 진짜 학습 모델(Student Head) 로드 완료!")
        
        # 🚀 [추가] 이 부분이 빠져서 에러가 났던 거예요!
    def infer(self, texts: list[str]):
        self.student.eval()
        with torch.no_grad():
            # 1. 텍스트를 모델이 이해할 수 있는 숫자로 변환
            inputs = self.tokenizer(
                texts, 
                padding=True, 
                truncation=True, 
                max_length=self.max_len, 
                return_tensors="pt"
            ).to(self.device)

            # 2. 모델 예측 실행
            logits = self.student(inputs["input_ids"], inputs["attention_mask"])
            
            # 3. 결과값 정제 (0~1 사이 확률로 변환 후 0.5 기준으로 0 또는 1 결정)
            probs = torch.sigmoid(logits).cpu().numpy()
            labels = (probs > 0.5).astype(int)
            
            return probs, labels

# --- 3. Platform Scrapers ---

class MusinsaPerfectScraper:
    def __init__(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    def run(self, url):
        try:
            self.driver.get(url)
            wait = WebDriverWait(self.driver, 15)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[class*='FixedArea__Inner']")))
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            fixed = soup.select_one("div[class*='FixedArea__Inner']")
            if not fixed: return {}
            
            return {
                'product_name': fixed.select_one('span[class*="GoodsName"]').get_text(strip=True) if fixed.select_one('span[class*="GoodsName"]') else "Unknown",
                'discount_rate': fixed.select_one('span[class*="Price__DiscountRate"]').get_text(strip=True) if fixed.select_one('span[class*="Price__DiscountRate"]') else "0",
                'rating': fixed.select_one('div[class*="ReviewSummary__Wrap"] span[class*="text-body"]').get_text(strip=True) if fixed.select_one('div[class*="ReviewSummary__Wrap"]') else "0",
                'review_count': fixed.select_one('div[class*="ReviewSummary__Wrap"] span[class*="underline"]').get_text(strip=True) if fixed.select_one('div[class*="ReviewSummary__Wrap"]') else "0",
                'product_likes': fixed.select_one('div[class*="Like__Container"] span').get_text(strip=True) if fixed.select_one('div[class*="Like__Container"]') else "0"
            }
        except Exception as e:
            print(f"Musinsa Error: {e}")
            return {}
        finally:
            self.driver.quit()

class ZigzagDetailCrawler:
    def __init__(self):
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    def crawl_detail(self, url):
        try:
            self.driver.get(url)
            time.sleep(3)
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            return {
                'product_name': soup.select_one('div.pdp__title h1').get_text(strip=True) if soup.select_one('div.pdp__title h1') else "Unknown",
                'discount_rate': soup.select_one('div[class*="css-1fwo2a0"]').get_text(strip=True) if soup.select_one('div[class*="css-1fwo2a0"]') else "0",
                'rating': soup.select_one('span[class*="eic0mh2"]').get_text(strip=True) if soup.select_one('span[class*="eic0mh2"]') else "0",
                'review_count': soup.select_one('span[class*="zds4_lh8eqt5"]').get_text(strip=True) if soup.select_one('span[class*="zds4_lh8eqt5"]') else "0"
            }
        except Exception as e:
            print(f"Zigzag Error: {e}")
            return {}
        finally:
            self.driver.quit()

def crawl_ably(url):
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    # 에이블리는 봇 차단이 심해서 유저 에이전트 설정이 중요해!
    options.add_argument("user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    try:
        driver.get(url)
        # 페이지 로딩 대기 (최대 10초)
        wait = WebDriverWait(driver, 10)
        
        # 제목이 나타날 때까지 기다리기
        try:
            title_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'h2, .typography__body1')))
            product_name = title_el.text
        except:
            product_name = "제목 추출 실패"

        page_text = driver.find_element(By.TAG_NAME, "body").text
        
        # 데이터 정리
        product_data = {
            'product_name': product_name,
            'discount_rate': "0", # 기본값
            'review_count': "0",
            'is_direct_shipping': 1 if '오늘출발' in page_text else 0
        }

        # 할인율 추출 (있을 경우만)
        price_elements = driver.find_elements(By.CLASS_NAME, "color__pink30")
        if price_elements:
            product_data['discount_rate'] = price_elements[0].text

        # 리뷰 수 추출
        count_match = re.search(r'리뷰\s*([\d,]+)개', page_text)
        if count_match:
            product_data['review_count'] = count_match.group(1)

        return product_data

    except Exception as e:
        print(f"Ably Parsing Error: {e}")
        return {} # 에러 나면 빈 딕셔너리 반환해서 500 에러 방지
    finally:
        driver.quit()

# --- 4. Core Parsing & Integration ---

def detect_platform(url):
    url_lower = url.lower() # 대소문자 섞여 있어도 상관없게!
    
    if "a-bly" in url_lower or "ably" in url_lower:
        return "ably"
    elif "musinsa" in url_lower:
        return "musinsa"
    elif "zigzag" in url_lower:
        return "zigzag"
    else:
        # 에러 날 때 어떤 주소가 들어왔는지 터미널에 찍어줘서 확인하기 쉽게!
        print(f"DEBUG: 인식 실패한 URL -> {url}") 
        raise ValueError(f"지원하지 않는 플랫폼 주소입니다: {url}")

# 전역 변수로 모델 선언
_INFER_MODEL = None

def extract_features_from_url(url, model_path="./student_distilled_e5_rule"):
    global _INFER_MODEL
    
    try:
        # 1. 모델 로드 (없을 때만 딱 한 번 실행)
        if _INFER_MODEL is None:
            if os.path.exists(model_path):
                print("🚀 모델을 처음 로드합니다. 잠시만 기다려 주세요...")
                _INFER_MODEL = KeywordAxisInfer(model_dir=model_path)
            else:
                print(f"⚠️ 모델 경로 없음: {model_path}")

        # 2. 플랫폼 감지
        platform = detect_platform(url)
    
        # 3. 데이터 크롤링 (이 부분은 if문 밖으로 나와야 매번 실행됨!)
        if platform == "musinsa":
            raw_data = MusinsaPerfectScraper().run(url)
        elif platform == "zigzag":
            raw_data = ZigzagDetailCrawler().crawl_detail(url)
        elif platform == "ably":
            raw_data = crawl_ably(url)
        else:
            raw_data = {}

        # 4. 데이터 정규화
        product_name = raw_data.get("product_name") or raw_data.get("name") or "Unknown"
    
        def clean_num(val):
            if not val: return 0
            num = re.sub(r'[^0-9]', '', str(val))
            return int(num) if num else 0

        result = {
            "platform": platform,
            "product_name": product_name,
            "discount_rate": clean_num(raw_data.get("discount_rate")),
            "review_count": clean_num(raw_data.get("review_count")),
            "rating": raw_data.get("rating") or raw_data.get("review_rating") or "0",
            "is_direct_shipping": raw_data.get("is_direct_shipping", 0)
        }

        # 5. 심리 축 분석 (로드된 전역 모델 _INFER_MODEL 사용)
        SIM_COLS = ["sim_quality_logic", "sim_trend_hype", "sim_temptation", "sim_fit_anxiety", "sim_bundle", "sim_confidence"]
        
        if _INFER_MODEL is not None:
            # ✅ 여기서 새로 생성하지 않고 전역 모델을 사용함!
            _, labels = _INFER_MODEL.infer([product_name])
            for i, col in enumerate(SIM_COLS):
                result[col] = int(labels[0][i]) if i < len(labels[0]) else 0
        else:
            # 모델 로드 실패 시 기본값 0 세팅
            for col in SIM_COLS: result[col] = 0

        return result

    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        return {"product_name": "Error", "details": str(e)}