import re
import json
import time
import os
import pandas as pd
import numpy as np
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModel

# --- 1. KeywordAxisInfer Implementation (PyTorch + HuggingFace) ---
def mean_pool(last_hidden_state, attention_mask):
    mask = attention_mask.unsqueeze(-1).type_as(last_hidden_state)
    summed = (last_hidden_state * mask).sum(dim=1)
    counts = mask.sum(dim=1).clamp(min=1e-9)
    return summed / counts

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
        scores = self.head(pooled)
        return scores

def load_runtime_config(model_dir: str):
    cfg_path = os.path.join(model_dir, "config_runtime.json")
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)

def apply_rules(text: str, AXES, RULES):
    t = str(text).lower()
    scores = np.zeros(len(AXES), dtype=np.float32)
    for j, ax in enumerate(AXES):
        for kw in RULES.get(ax, []):
            target = str(kw).lower()

            # 울 예외: "겨울" 포함된 문맥은 울 무시
            if target == "울":
                clean = t.replace("겨울", " ")
                if "울" in clean:
                    if ax == "quality_logic":
                        scores[j] = 1.0
                    break
                else:
                    continue

            if target in t:
                scores[j] = 1.0
                break
    return scores

class KeywordAxisInfer:
    def __init__(self, model_dir: str, device: str | None = None):
        self.model_dir = model_dir
        self.cfg = load_runtime_config(model_dir)

        self.AXES = self.cfg["AXES"]
        self.THRESHOLDS = self.cfg["THRESHOLDS"]
        self.RULES = self.cfg["RULES"]
        self.rule_weight = float(self.cfg.get("rule_weight", 1.2))
        self.max_len = int(self.cfg.get("max_len", 128))
        dropout = float(self.cfg.get("dropout", 0.0))

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        base_name = self.cfg.get("STUDENT_NAME", "intfloat/multilingual-e5-base")

        # ✅ tokenizer/encoder 둘 다 base_name에서 로드
        self.tokenizer = AutoTokenizer.from_pretrained(base_name)
        self.encoder = AutoModel.from_pretrained(base_name).to(self.device)

        hidden = self.encoder.config.hidden_size
        self.student = StudentDistillModel(
            self.encoder, hidden_size=hidden, out_dim=len(self.AXES), dropout=dropout
        ).to(self.device)

        head_path = os.path.join(model_dir, "student_head.pt")
        state = torch.load(head_path, map_location=self.device)

        # ✅ head만 로드 (저장 형태 2가지 모두 대응)
        # 1) {"weight":..., "bias":...}
        if "weight" in state and "bias" in state:
            self.student.head.load_state_dict(state, strict=True)
        # 2) {"head.weight":..., "head.bias":...} 혹은 전체 state_dict
        else:
            # head.* 만 추출해서 로드 시도
            head_state = {k.replace("head.", ""): v for k, v in state.items() if k.startswith("head.")}
            if head_state:
                self.student.head.load_state_dict(head_state, strict=True)
            else:
                # 마지막 수단: 전체 로드(학습 때 전체 저장했으면 여기서 성공)
                self.student.load_state_dict(state, strict=False)

        self.student.eval()

    @torch.no_grad()
    def predict_scores(self, texts, batch_size: int = 128):
        outs = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            enc = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_len,
                return_tensors="pt"
            )
            input_ids = enc["input_ids"].to(self.device)
            attn = enc["attention_mask"].to(self.device)

            s = self.student(input_ids, attn)  # (B,6)
            outs.append(s.detach().cpu().numpy())
        return np.vstack(outs).astype(np.float32)

    def infer(self, texts, batch_size: int = 128):
        student_scores = self.predict_scores(texts, batch_size=batch_size)
        rule_scores = np.vstack([apply_rules(t, self.AXES, self.RULES) for t in texts])

        final_scores = student_scores + self.rule_weight * rule_scores

        final_labels = np.zeros_like(final_scores, dtype=np.int32)
        for j, ax in enumerate(self.AXES):
            final_labels[:, j] = (final_scores[:, j] >= float(self.THRESHOLDS[ax])).astype(np.int32)

        return final_scores, final_labels

# --- 2. Crawler Functions ---
def detect_platform(url):
    if "a-bly.com" in url:
        return "ably"
    elif "musinsa.com" in url:
        return "musinsa"
    elif "zigzag.kr" in url:
        return "zigzag"
    else:
        raise ValueError("지원하지 않는 플랫폼입니다.")

class MusinsaPerfectScraper:
    def __init__(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    def run(self, url):
        self.result = {}
        try:
            self.driver.get(url)
            wait = WebDriverWait(self.driver, 15)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[class*='FixedArea__Inner']")))
            self.driver.execute_script("window.scrollTo(0, 800);")
            time.sleep(2)

            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            fixed = soup.select_one("div[class*='FixedArea__Inner']")

            if fixed:
                self.result['category'] = " > ".join([a.get_text(strip=True) for a in fixed.select('div[class*="Category__Wrap"] a')])
                self.result['brand'] = self._text(fixed, 'span[class*="Brand__BrandName"]')
                self.result['name'] = self._text(fixed, 'span[class*="GoodsName"]')
                
                self.result['review_score'] = self._text(fixed, 'div[class*="ReviewSummary__Wrap"] span[class*="text-body"]')
                self.result['review_count'] = self._text(fixed, 'div[class*="ReviewSummary__Wrap"] span[class*="underline"]')
                self.result['discount_rate'] = self._text(fixed, 'span[class*="Price__DiscountRate"]')
                
                sale_price_text = self._text(fixed, 'span[class*="Price__CalculatedPrice"]')
                self.result['discounted_price'] = int(re.sub(r'[^0-9]', '', sale_price_text)) if sale_price_text else 0
                arrival_info = fixed.select_one('div[class*="PlusDeliveryArrivalInfo__Wrapper"]')
                self.result['shipping_info'] = arrival_info.get_text(" ", strip=True) if arrival_info else ""
                self.result['product_likes'] = self._text(fixed, 'div[class*="Like__Container"] span')
                
                # is_direct_shipping
                self.result['is_direct_shipping'] = 1 if "플러스배송" in self.result['shipping_info'] or "도착 보장" in self.result['shipping_info'] else 0

            return self.result
        except Exception as e:
            print(f"❌ Musinsa Error: {e}")
            return {}

    def _text(self, parent, selector):
        tag = parent.select_one(selector)
        return tag.get_text(strip=True) if tag else ""

    def close(self):
        self.driver.quit()

class ZigzagDetailCrawler:
    def __init__(self):
        self.chrome_options = Options()
        self.chrome_options.add_argument('--headless')
        self.chrome_options.add_argument('--no-sandbox')
        self.chrome_options.add_argument('--disable-dev-shm-usage')
        self.chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=self.chrome_options)

    def _expand_product_info(self):
        try:
            more_button = WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located((By.XPATH, "//button[contains(., '상품정보 더 보기')]"))
            )
            self.driver.execute_script("arguments[0].click();", more_button)
            time.sleep(2)
        except Exception:
            pass

    def _safe_get_text(self, soup, selector):
        element = soup.select_one(selector)
        return element.get_text(strip=True) if element else None

    def crawl_detail(self, url):
        self.driver.get(url)
        time.sleep(3)
        self._expand_product_info()
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        data = {}

        data['name'] = self._safe_get_text(soup, 'div.pdp__title h1')
        data['discount_rate'] = self._safe_get_text(soup, 'div[class*="css-1fwo2a0"]')
        
        benefit_price_box = soup.select_one('div[class*="css-1ig1bns"] div[class*="e1sus6ys1"]')
        normal_price_box = soup.select_one('div[class*="css-vogdud"] div[class*="e1sus6ys1"]')
        target_price_element = benefit_price_box if benefit_price_box else normal_price_box
        if target_price_element:
            sale_text = target_price_element.get_text(strip=True)
            data['discounted_price'] = int(re.sub(r'[^0-9]', '', sale_text))
        else:
            data['discounted_price'] = 0

        # 브랜드명 및 카테고리 추출 시도
        data['brand'] = self._safe_get_text(soup, 'h2[class*="e1qy47wz6"]') # 스토어명을 브랜드로 매핑
        cats = [a.get_text(strip=True) for a in soup.select('div[class*="breadcrumb"] a, a[class*="breadcrumb"]')]
        data['category'] = " > ".join(cats) if cats else "Unknown"

        is_zdelivery = soup.select_one('svg[data-zds-graphic="LogoZdelivery"]')
        data['is_direct_shipping'] = 1 if is_zdelivery else 0
        
        data['review_score'] = self._safe_get_text(soup, 'span[class*="eic0mh2"]')
        data['review_count'] = self._safe_get_text(soup, 'span[class*="zds4_lh8eqt5"]')
        
        # 조회수 기반 임시 좋아요 대용
        view_text = self._safe_get_text(soup, 'div[class*="css-hjgjo9"]')
        if view_text:
            numbers = re.sub(r'[^0-9]', '', view_text)
            data['product_likes'] = numbers if numbers else "0"
        else:
            data['product_likes'] = "0"
            
        return data

    def close(self):
        self.driver.quit()

def crawl_ably(url):
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,2000')
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
    prefs = {"profile.managed_default_content_settings.images": 2}
    options.add_experimental_option("prefs", prefs)
    options.add_argument('--log-level=3')

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    try:
        driver.get(url)
        time.sleep(5)
        for scroll in [1000, 2000]:
            driver.execute_script(f"window.scrollTo(0, {scroll});")
            time.sleep(1.5)

        product_data = {}
        try:
            title_tag = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'h2, p.typography__body1')))
            product_data['name'] = title_tag.text
        except:
            product_data['name'] = "제목 없음"
            
        try:
            # 카테고리
            cats = [a.text.strip() for a in driver.find_elements(By.CSS_SELECTOR, 'div[class*="breadcrumb"] a')]
            product_data['category'] = " > ".join(cats) if cats else "Unknown"
        except:
            product_data['category'] = "Unknown"

        try:
            # 브랜드(마켓명)
            market_name = driver.find_element(By.CSS_SELECTOR, 'div[class*="MarketName"], span[class*="MarketName"], h1[class*="MarketName"]').text
            product_data['brand'] = market_name.strip()
        except:
            product_data['brand'] = "Unknown"

        try:
            price_container = driver.find_element(By.CLASS_NAME, "sc-ad5f1e6f-0")
            discount_rate_el = price_container.find_elements(By.CLASS_NAME, "color__pink30")
            product_data['discount_rate'] = discount_rate_el[0].text.replace('%', '').strip() if discount_rate_el else "0"
            
            # 할인된 가격
            price_el = price_container.find_elements(By.CLASS_NAME, "color__gray100")
            if not price_el:
                 price_el = driver.find_elements(By.CSS_SELECTOR, ".sc-ad5f1e6f-0 span, .sc-9f653767-0 span")
            
            sale_price = 0
            for el in price_el:
                 text = el.text.strip()
                 if text and text[-1] == '원' and ',' in text:
                     sale_price = int(re.sub(r'[^0-9]', '', text))
                     break
            product_data['discounted_price'] = sale_price
        except:
             product_data['discount_rate'] = "0"
             product_data['discounted_price'] = 0

        try:
            page_text = driver.find_element(By.TAG_NAME, "body").text
            count_match = re.search(r'리뷰\s*([\d,]+)개', page_text)
            if count_match:
                product_data['review_count'] = int(count_match.group(1).replace(',', ''))
            else:
                product_data['review_count'] = 0
            
            score_match = re.search(r'([\d.]+)%가\s*만족한', page_text)
            if score_match:
                raw_percent = float(score_match.group(1))
                product_data['review_score'] = round(max(0, (raw_percent - 50) / 10), 2)
            else:
                product_data['review_score'] = 0.0
        except:
            product_data['review_count'] = 0
            product_data['review_score'] = 0.0

        try:
            likes_container = driver.find_element(By.CLASS_NAME, "sc-45b21edb-3")
            likes_text = likes_container.find_element(By.CLASS_NAME, "color__pink30").text.strip()
            if '만' in likes_text:
                product_data['product_likes'] = str(int(float(likes_text.replace('만', '')) * 10000))
            else:
                 product_data['product_likes'] = likes_text.replace(',', '')
        except:
            product_data['product_likes'] = "0"

        product_data['is_direct_shipping'] = 1 if '오늘출발' in page_text else 0
        return product_data
    except Exception as e:
        print(f"Ably Error: {e}")
        return {}
    finally:
        driver.quit()

def crawl_product_data(url, platform):
    print(f"Crawling {url} on {platform}...")
    data = {}
    
    if platform == "musinsa":
        crawler = MusinsaPerfectScraper()
        try:
            data = crawler.run(url)
        finally:
            crawler.close()
    elif platform == "zigzag":
        crawler = ZigzagDetailCrawler()
        try:
            data = crawler.crawl_detail(url)
        finally:
            crawler.close()
    elif platform == "ably":
        data = crawl_ably(url)
    else:
        return {}

    # Normalize Data
    normalized_data = {}
    normalized_data["platform"] = platform
    normalized_data["category"] = data.get("category", "Unknown")
    normalized_data["brand"] = data.get("brand", "Unknown")
    normalized_data["name"] = data.get("name", "Unknown")
    normalized_data["discounted_price"] = int(data.get("discounted_price", 0))

    dr = data.get("discount_rate", "0")
    if isinstance(dr, str): dr = re.sub(r'[^0-9]', '', dr)
    normalized_data["discount_rate"] = int(dr) if dr else 0
    
    rs = data.get("review_score", "0")
    if isinstance(rs, str): rs = re.sub(r'[^0-9.]', '', rs)
    normalized_data["review_score"] = float(rs) if rs else 0.0
    
    rc = data.get("review_count", "0")
    if isinstance(rc, str): rc = re.sub(r'[^0-9]', '', rc)
    normalized_data["review_count"] = int(rc) if rc else 0
    
    likes = data.get("product_likes", "0")
    if isinstance(likes, str):
        if '만' in likes: likes = str(int(float(likes.replace('만', '')) * 10000))
        likes = re.sub(r'[^0-9]', '', likes)
    normalized_data["product_likes"] = int(likes) if likes else 0
    
    normalized_data["is_direct_shipping"] = int(data.get("is_direct_shipping", 0))
    
    return normalized_data

# --- 3. Main Feature Extraction (Integration) ---
def extract_features_from_url(url, sim_model=None):
    platform = detect_platform(url)
    product_data = crawl_product_data(url, platform)
    
    # Binary Features using sim_model
    product_name = product_data.get("name", "")
    binary_features = {}
    
    SIM_COLS = [
        "sim_quality_logic",
        "sim_trend_hype",
        "sim_temptation",
        "sim_fit_anxiety",
        "sim_bundle",
        "sim_confidence"
    ]
    
    if sim_model and product_name != "Unknown":
        try:
            scores, labels = sim_model.infer([product_name])
            for i, col in enumerate(SIM_COLS):
                if i < len(labels[0]):
                    binary_features[col] = int(labels[0][i])
                else:
                    binary_features[col] = 0
        except Exception as e:
             print(f"Model Inference Error: {e}")
             binary_features = {col: 0 for col in SIM_COLS}
    else:
        binary_features = {col: 0 for col in SIM_COLS}

    # Final feature dictionary with requested keys
    feature_dict = {
        "discount_rate": product_data.get("discount_rate", 0),
        "review_score": product_data.get("review_score", 0.0),
        "review_count": product_data.get("review_count", 0),
        "product_likes": product_data.get("product_likes", 0),
        "platform": product_data.get("platform", platform),
        "is_direct_shipping": product_data.get("is_direct_shipping", 0),
        "category": product_data.get("category", "Unknown"),
        "brand": product_data.get("brand", "Unknown"),
        "name": product_data.get("name", "Unknown"),
        "할인 후 가격": product_data.get("discounted_price", 0),
        **binary_features
    }

    return feature_dict

# --- 4. Execution ---
if __name__ == "__main__":
    # 모델 로드 (상대 경로 사용)
    model_path = "./student_distilled_e5_rule"
    if os.path.exists(model_path):
        infer_model = KeywordAxisInfer(model_path)
    else:
        print(f"Warning: Model path {model_path} not found.")
        infer_model = None

    # 테스트 URLs
    test_urls = [
        # "https://m.a-bly.com/goods/3129076",
        "https://zigzag.kr/catalog/products/122935080",
        # "https://www.musinsa.com/products/4457092"
    ]

    results = []
    for test_url in test_urls:
        print(f"\nProcessing: {test_url}")
        result_dict = extract_features_from_url(test_url, sim_model=infer_model)
        results.append(result_dict)

    if results:
        final_df = pd.DataFrame(results)
        print("\n=== Final Extracted Features ===")
        # Print transposed for better readability of wide data
        pd.set_option('display.max_columns', None)
        print(final_df)
