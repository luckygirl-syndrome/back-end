# --- 1. Imports ---
import time
import re
import json
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

# --- 2. KeywordAxisInfer Implementation ---
class KeywordAxisInfer:
    """
    KeywordAxisInfer 클래스: 상품명에서 키워드를 추출하여 심리 축(Sim Columns) 분석
    """
    def __init__(self, model_path):
        self.model_path = model_path
        self.config = self._load_config()
        self.axes = self.config.get("AXES", [])
        self.rules = self.config.get("RULES", {})

    def _load_config(self):
        config_path = os.path.join(self.model_path, "config_runtime.json")
        if not os.path.exists(config_path):
            return {"AXES": [], "RULES": {}}
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def infer(self, texts):
        scores = []
        labels = []
        for text in texts:
            text_str = str(text)
            row_scores = []
            for axis in self.axes:
                keywords = self.rules.get(axis, [])
                # 언니가 요청한 'ㅇㅇ핏' 등의 규칙이 여기에 반영됨
                matched = any(keyword in text_str for keyword in keywords)
                score = 1.0 if matched else 0.0
                row_scores.append(score)
            scores.append(row_scores)
            labels.append(row_scores)
        return np.array(scores), np.array(labels)

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
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    try:
        driver.get(url)
        time.sleep(5)
        page_text = driver.find_element(By.TAG_NAME, "body").text
        title_tag = driver.find_elements(By.CSS_SELECTOR, 'h2, p.typography__body1')
        product_data = {'product_name': title_tag[0].text if title_tag else "제목 없음"}
        
        price_el = driver.find_elements(By.CLASS_NAME, "color__pink30")
        product_data['discount_rate'] = price_el[0].text if price_el else "0"
        
        count_match = re.search(r'리뷰\s*([\d,]+)개', page_text)
        product_data['review_count'] = count_match.group(1) if count_match else "0"
        product_data['is_direct_shipping'] = 1 if '오늘출발' in page_text else 0
        return product_data
    except Exception as e:
        print(f"Ably Error: {e}")
        return {}
    finally:
        driver.quit()

# --- 4. Core Parsing & Integration ---

def detect_platform(url):
    if "a-bly.com" in url: return "ably"
    elif "musinsa.com" in url: return "musinsa"
    elif "zigzag.kr" in url: return "zigzag"
    raise ValueError("지원하지 않는 플랫폼 주소입니다.")

def extract_features_from_url(url, model_path="./student_distilled_e5_rule"):
    platform = detect_platform(url)
    
    # 데이터 크롤링
    if platform == "musinsa":
        raw_data = MusinsaPerfectScraper().run(url)
    elif platform == "zigzag":
        raw_data = ZigzagDetailCrawler().crawl_detail(url)
    elif platform == "ably":
        raw_data = crawl_ably(url)
    else:
        raw_data = {}

    # 데이터 정규화 (숫자 변환 등)
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

    # 심리 축 분석 (모델 로직 연동)
    SIM_COLS = ["sim_quality_logic", "sim_trend_hype", "sim_temptation", "sim_fit_anxiety", "sim_bundle", "sim_confidence"]
    if os.path.exists(model_path):
        infer_model = KeywordAxisInfer(model_path)
        _, labels = infer_model.infer([product_name])
        for i, col in enumerate(SIM_COLS):
            result[col] = int(labels[0][i]) if i < len(labels[0]) else 0
    else:
        for col in SIM_COLS: result[col] = 0

    return result