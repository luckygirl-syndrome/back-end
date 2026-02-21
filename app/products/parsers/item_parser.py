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
from .model_utils import KeywordAxisInfer
import traceback

# --- 3. Platform Scrapers ---

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
        # 🛡️ 1. try 문 밖에서 가장 먼저 빈 바구니를 만듭니다. (에러 방지용)
        self.result = {
            'product_img': "", 'profile_img': "", 'product_name': "Unknown", 
            'brand': "Unknown", 'category': "Unknown", 'discounted_price': 0,
            'review_score': "0", 'review_count': "0", 'discount_rate': "0",
            'is_direct_shipping': 0, 'product_likes': "0"
        }

        try:
            print("📍 [Step 1] 브라우저 실행 중...")
            self.driver.get(url)
            print("📍 [Step 2] 페이지 접속 완료, 대기 중...")
            wait = WebDriverWait(self.driver, 15)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # 1. 이미지 추출 (순서: 메타 태그 -> 클래스 백업) ✅
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                self.result['product_img'] = og_image["content"]
            
            # 2. 고정 영역 데이터 파싱
            fixed = soup.select_one("div[class*='FixedArea__Inner']")
            if fixed:
                # 이미지가 아직 비어있을 때만 클래스로 재시도
                if not self.result['product_img']:
                    img_tag = fixed.select_one('div[class*="Thumbnail"] img')
                    self.result['product_img'] = img_tag['src'] if img_tag else ""

                # 브랜드 로고(profile_img) 추가 ✅
                logo_tag = fixed.select_one('div[class*="Brand__BrandLogo"] img')
                self.result['profile_img'] = logo_tag['src'] if logo_tag else ""

                # 기본 정보
                self.result['category'] = " > ".join([a.get_text(strip=True) for a in fixed.select('div[class*="Category__Wrap"] a')])
                self.result['brand'] = self._text(fixed, 'span[class*="Brand__BrandName"]')
                self.result['product_name'] = self._text(fixed, 'span[class*="GoodsName"]')

                # 리뷰 및 가격
                self.result['review_score'] = self._text(fixed, 'div[class*="ReviewSummary__Wrap"] span[class*="text-body"]')
                self.result['review_count'] = self._text(fixed, 'div[class*="ReviewSummary__Wrap"] span[class*="underline"]')
                self.result['discount_rate'] = self._text(fixed, 'span[class*="Price__DiscountRate"]')
                
                sale_text = self._text(fixed, 'span[class*="Price__CalculatedPrice"]')
                self.result['discounted_price'] = int(re.sub(r'[^0-9]', '', sale_text)) if sale_text else 0
                
                # 배송 정보 및 좋아요
                arrival = fixed.select_one('div[class*="PlusDeliveryArrivalInfo__Wrapper"]')
                shipping_info = arrival.get_text(" ", strip=True) if arrival else ""
                self.result['is_direct_shipping'] = 1 if any(x in shipping_info for x in ["플러스배송", "도착 보장"]) else 0
                self.result['product_likes'] = self._text(fixed, 'div[class*="Like__Container"] span')

            return self.result
        except Exception as e:
            print(f"❌ Musinsa Error: {e}")
            return self.result

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

        og_image = soup.find("meta", property="og:image")
        data['product_img'] = og_image["content"] if og_image else ""

        data['product_name'] = self._safe_get_text(soup, 'div.pdp__title h1')
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

class AblyDetailCrawler:
    def __init__(self):
        self.chrome_options = Options()
        self.chrome_options.add_argument('--headless')
        self.chrome_options.add_argument('--no-sandbox')
        self.chrome_options.add_argument('--disable-dev-shm-usage')
        self.chrome_options.add_argument('--disable-gpu')
        # 에이블리는 모바일 에이전트가 제일 정확해
        self.chrome_options.add_argument("user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=self.chrome_options)

    def crawl_detail(self, url):
        # 1. 초기 바구니 설정
        data = {
            'product_name': "Unknown", 'brand': "Unknown", 'category': "Unknown",
            'product_img': "", 'profile_img': "",
            'discounted_price': 0, 'discount_rate': "0",
            'review_count': 0, 'review_score': 0.0,
            'product_likes': "0", 'is_direct_shipping': 0
        }

        try:
            self.driver.get(url)
            time.sleep(5)
            
            # 스크롤 로직 (Lazy 로딩 대응)
            for scroll in [1000, 2000]:
                self.driver.execute_script(f"window.scrollTo(0, {scroll});")
                time.sleep(1)

            soup = BeautifulSoup(self.driver.page_source, 'html.parser')

            # 2. 이미지 & 제목 (메타 태그)
            og_image = soup.find("meta", property="og:image")
            data['product_img'] = og_image["content"] if og_image else ""
            
            og_title = soup.find("meta", property="og:title")
            data['product_name'] = og_title["content"] if og_title else "제목 없음"

            # 3. 브랜드 & 가격 & 리뷰 (텍스트 및 셀렉터 혼합)
            page_text = self.driver.find_element(By.TAG_NAME, "body").text
            
            # 가격 필살기
            price_matches = re.findall(r'([\d,]+)원', page_text)
            if price_matches:
                data['discounted_price'] = int(price_matches[0].replace(',', ''))

            # 브랜드명
            try:
                market_el = self.driver.find_element(By.CSS_SELECTOR, 'a[href*="/market/"] span, [class*="MarketName"]')
                data['brand'] = market_el.text.strip()
            except:
                desc = soup.find("meta", property="og:description")
                if desc: data['brand'] = desc['content'].split(' ')[0]

            # 배송 정보
            data['is_direct_shipping'] = 1 if '오늘출발' in page_text else 0

            return data

        except Exception as e:
            print(f"❌ Ably Crawler Error: {e}")
            return data

    def close(self):
        self.driver.quit()

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
        crawler = AblyDetailCrawler()
        try:
            data = crawler.crawl_detail(url)
        finally:
            crawler.close() 
    else:
        return {}

    # Normalize Data
    normalized_data = {}
    normalized_data["product_img"] = data.get("product_img", "")
    normalized_data["platform"] = platform
    normalized_data["category"] = data.get("category", "Unknown")
    normalized_data["brand"] = data.get("brand", "Unknown")
    normalized_data["product_name"] = data.get("product_name", "Unknown")
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

def extract_features_from_url(url):
    global _INFER_MODEL
    model_dir = "./student_distilled_e5_rule"
    
    try:
        # 1. 모델 싱글톤 로드 (최초 1회)
        if _INFER_MODEL is None:
            if os.path.exists(model_dir):
                _INFER_MODEL = KeywordAxisInfer(model_dir=model_dir)

        # 2. 플랫폼 감지
        platform = detect_platform(url)
    
        # 3. 크롤링 및 데이터 정규화 (위에 정의한 통합 함수 호출!) ✅
        result = crawl_product_data(url, platform)

        # ✅ 안전하게 상품명을 변수에 담기 (변수 선언!)
        p_name = result.get("product_name", "Unknown")

        if not result or p_name == "Unknown":
            return {"product_name": "Error", "details": "데이터를 가져오지 못했습니다."}

        # 4. 심리 축 분석 (NLP 추론)
        SIM_COLS = ["sim_quality_logic", "sim_trend_hype", "sim_temptation", 
                    "sim_fit_anxiety", "sim_bundle", "sim_confidence"]
        
        if _INFER_MODEL is not None:
            # result["name"]을 사용해서 심리 축 파악
            _, labels = _INFER_MODEL.infer([result["product_name"]])
            for i, col in enumerate(SIM_COLS):
                result[col] = int(labels[0][i]) if i < len(labels[0]) else 0
        else:
            for col in SIM_COLS: result[col] = 0

        # 최종 결과 반환
        return result

    except Exception as e:
        # ❌ 단순히 e만 찍지 말고, 어디서 터졌는지 전체 경로를 다 찍어보자!
        print("--- 에러 상세 경로 시작 ---")
        print(traceback.format_exc()) 
        print("--- 에러 상세 경로 끝 ---")
        return {"product_name": "Error", "details": str(e)}