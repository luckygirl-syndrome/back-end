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
import undetected_chromedriver as uc

import datetime
import random



# --- 3. Platform Scrapers ---

class MusinsaPerfectScraper:
    def __init__(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        
        # 🚩 핵심: 봇 감지 우회 옵션들
        chrome_options.add_argument('--disable-blink-features=AutomationControlled') 
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
    
        # 서버 환경에서 흔한 리눅스 UA가 아니라, 맥북 유저인 척 하기
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36')
    
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
        # 🚩 자바스크립트로 "나 로봇 아니야"라고 한 번 더 확인시켜주기
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    def run(self, url):
        self.result = {
            'product_img': "", 'profile_img': "", 'product_name': "Unknown", 
            'brand': "Unknown", 'category': "Unknown", 'discounted_price': 0,
            'review_score': "0", 'review_count': "0", 'discount_rate': "0",
            'free_shipping': 1, 'is_direct_shipping': 0, 'product_likes': "0"
        }

        try:
            print("📍 [Step 1] 브라우저 접속...")
            self.driver.get(url)
            
            # 1. 서버 속도 고려해서 넉넉히 대기 (데이터가 화면에 그려질 시간)
            time.sleep(3) 

            # 🚩 [필살기] 자바스크립트로 화면에 떠 있는 글자 직접 추출하기
            # BeautifulSoup이 못 읽는 데이터도 브라우저에 떠 있으면 다 긁어옴!
            js_script = """
            return {
                name: document.querySelector('span[class*="GoodsName"], .title, h2')?.innerText,
                brand: document.querySelector('span[class*="Brand__BrandName"], .brand')?.innerText,
                price: document.querySelector('span[class*="Price__CalculatedPrice"], .price')?.innerText,
                likes: document.querySelector('div[class*="Like__Container"] span, [class*="like_count"]')?.innerText,
                category: Array.from(document.querySelectorAll('div[class*="Category__Wrap"] a, .breadcrumb a')).map(a => a.innerText).join(' > '),
                og_title: document.querySelector('meta[property="og:title"]')?.content,
                og_image: document.querySelector('meta[property="og:image"]')?.content
            };
            """
            extracted = self.driver.execute_script(js_script)
            print(f"📍 [Step 2] JS 추출 성공: {extracted.get('name')}")

            # 2. 추출된 데이터를 바구니에 매핑
            if extracted:
                # 상품명 (JS 추출값 우선, 없으면 OG 태그)
                self.result['product_name'] = extracted.get('name') or (extracted.get('og_title') or "Unknown").split(' - ')[0]
                self.result['brand'] = extracted.get('brand') or "Unknown"
                self.result['product_img'] = extracted.get('og_image') or ""
                
                # 가격 (숫자만 추출)
                p_text = re.sub(r'[^0-9]', '', extracted.get('price') or "0")
                self.result['discounted_price'] = int(p_text) if p_text else 0
                
                # 좋아요
                l_text = re.sub(r'[^0-9]', '', extracted.get('likes') or "0")
                self.result['product_likes'] = l_text if l_text else "0"
                
                # 카테고리
                self.result['category'] = extracted.get('category') or "Unknown"

            # 3. 배송 정보는 전체 텍스트에서 한 번 더 체크
            body_text = self.driver.find_element(By.TAG_NAME, "body").text
            self.result['is_direct_shipping'] = 1 if any(x in body_text for x in ["플러스배송", "도착 보장", "오늘출발"]) else 0

            # 클리닝
            for key in self.result:
                if isinstance(self.result[key], str):
                    self.result[key] = "".join(char for char in self.result[key] if char.isprintable()).strip()
            
            return self.result

        except Exception as e:
            print(f"❌ Musinsa 최종 에러: {e}")
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

        # 지그재그 배송 정보 추출 (직진배송 & 일반 무료배송 집중)
        try:
            # 1. 초기화
            data['is_direct_shipping'] = 0
            data['free_shipping'] = 0
    
            page_source = self.driver.page_source

            # 2. [직진배송] 판별 (LogoZdelivery만 타겟)
            # 소스코드에 로고 이름이 있거나, 실제 요소를 찾았을 때
            if 'LogoZdelivery' in page_source:
                data['is_direct_shipping'] = 1
                data['free_shipping'] = 1
            else:
                # 소스에 없더라도 실제 DOM에 로고가 있는지 한 번 더 체크
                try:
                    zdelivery_logo = self.driver.find_elements(By.CSS_SELECTOR, '[data-zds-graphic="LogoZdelivery"]')
                    if zdelivery_logo:
                        data['is_direct_shipping'] = 1
                        data['free_shipping'] = 1
                except: pass

            # 3. [일반 무료배송] 판별 (직진배송이 아닐 때만 검사)
            if data['is_direct_shipping'] == 0:
                try:
                    # '배송' 관련 키워드가 있는 아주 좁은 구역만 타겟팅
                    # 지그재그는 보통 '배송비' 글자 근처에 '무료' 혹은 '무료배송'이 적힘
                    delivery_el = self.driver.find_element(By.XPATH, "//div[contains(text(), '배송비')] | //span[contains(text(), '배송비')]")
                    # 배송비 글자가 포함된 부모 요소 전체의 텍스트를 확인
                    parent_text = delivery_el.find_element(By.XPATH, "./..").text
            
                    if '무료배송' in parent_text:
                        data['free_shipping'] = 1
                except:
                    # 위에서 못 찾았을 경우에만 제한적으로 본문 앞부분 검색
                    # (추천 상품이나 하단 광고 텍스트에 낚이지 않기 위함)
                    body_start_text = self.driver.find_element(By.TAG_NAME, "body").text[:1500]
                    if '무료배송' in body_start_text:
                        data['free_shipping'] = 1

        except Exception as e:
            print(f"❌ 지그재그 배송 판별 오류: {e}")
        
        data['review_score'] = self._safe_get_text(soup, 'span[class*="eic0mh2"]')
        data['review_count'] = self._safe_get_text(soup, 'span[class*="zds4_lh8eqt5"]')
        
        ''' 지그재그는 찜이 없어서 그냥 찜 0으로 하겠음.
        # 조회수 기반 임시 좋아요 대용
        view_text = self._safe_get_text(soup, 'div[class*="css-hjgjo9"]')
        if view_text:
            numbers = re.sub(r'[^0-9]', '', view_text)
            data['product_likes'] = numbers if numbers else "0"
        else:
            data['product_likes'] = "0"
        '''    
        data['product_likes'] = "0"

        return data

    def close(self):
        self.driver.quit()

class AblyDetailCrawler:
    def __init__(self):
        # 1. 🚩 옵션 설정
        options = uc.ChromeOptions()
        
        # 서버용 필수 (최소화)
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        
        # 🚩 [모바일 위장] mobileEmulation 대신 UA와 사이즈로 승부!
        ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1"
        options.add_argument(f'--user-agent={ua}')
        options.add_argument('--window-size=390,844') # 아이폰 크기

        # 2. 🚩 드라이버 실행
        # 언니, 여기서 headless=True를 한 번 더 써주는 게 uc의 핵심이야!
        try:
            self.driver = uc.Chrome(options=options, headless=True, use_subprocess=True)
            print("✅ undetected-chromedriver 실행 성공!")
        except Exception as e:
            print(f"❌ uc 실행 실패: {e}")
            # 정 안되면 일반 셀레늄으로 백업하는 로직이라도 있어야 함
    def crawl_detail(self, url):
        data = {
            'product_name': "Unknown", 'brand': "Unknown", 'category': "Unknown",
            'product_img': "", 'profile_img': "",
            'discounted_price': 0, 'discount_rate': 0,
            'review_count': 0, 'review_score': 0.0,
            'free_shipping': 1,
            'product_likes': 0, 'is_direct_shipping': 0
        }

        try:
            # 1. 🚩 접속 전 세션 세탁 (에이블리 메인 들르기)
            self.driver.set_page_load_timeout(30)
            print(f"📍 [서버] 에이블리 세션 생성 중...")
            self.driver.get("https://www.a-bly.com") 
            time.sleep(random.uniform(1, 2))

            # 2. 헤더 강제 주입 (Referer 설정으로 인증 오류 돌파)
            self.driver.execute_cdp_cmd("Network.setExtraHTTPHeaders", {
                "headers": {
                    "Referer": "https://www.ably.com/",
                    "Origin": "https://www.ably.com",
                    "Accept-Language": "ko-KR,ko;q=0.9"
                }
            })

            print(f"📍 [서버] 상품 접속 시도: {url}")
            # crawl_detail 함수 안에서 주소 변경
            target_url = url.replace("m.a-bly.com", "www.a-bly.com")
            self.driver.get(target_url)

            # 3. 🚩 [핵심] 충분히 기다리기 (에이블리는 렌더링이 느려)
            time.sleep(7) 

            # 4. 🚩 무조건 스크린샷 찍기 (이름 고정해서 찾기 쉽게!)
            now = datetime.datetime.now().strftime("%H%M%S")
            filename = f"server_debug_{now}.png"
            self.driver.save_screenshot(filename)
            print(f"📸 [확인] 스크린샷 저장 완료 -> {filename}")
            
            try:
                self.driver.get(url)
            except Exception as e:
                print(f"⚠️ 접속 중 에러 발생했으나 사진은 찍음: {e}")

            time.sleep(5)
            
            now = datetime.datetime.now().strftime("%H%M%S")
            filename = f"server_debug_{now}.png"
            self.driver.save_screenshot(filename)
            print(f"📸 [확인] 스크린샷 저장 완료 -> {filename}")

            # 3. 추출 로직 시작 (전체를 큰 try로 감싸서 안전하게!)
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')

            # 🚀 [핵심] 3단계 스크롤 로직 (리뷰/찜수가 로딩될 기회를 줌)
            for offset in [1000, 2000, 3000]: 
                self.driver.execute_script(f"window.scrollTo(0, {offset});")
                time.sleep(1.5) # 각 스크롤 후 로딩 대기

            # 다시 맨 위로 살짝 올려서 상단 정보도 놓치지 않게 함
            self.driver.execute_script("window.scrollTo(0, 500);")
            time.sleep(1)

            soup = BeautifulSoup(self.driver.page_source, 'html.parser')

            # 1. 상품명 & 이미지 (메타 태그 + 셀렉터 백업)
            og_title = soup.find("meta", property="og:title")
            data['product_name'] = og_title["content"] if og_title else "제목 없음"
            
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                data['product_img'] = og_image["content"]
            else:
                # 메타 태그 실패 시 실제 img 태그 찾기
                try:
                    img_el = self.driver.find_element(By.CSS_SELECTOR, 'div[class*="Image"] img, img[class*="ProductImage"]')
                    data['product_img'] = img_el.get_attribute("src")
                except: pass

            # 2. 브랜드명
            try:
                # 에이블리/지그재그 공통 마켓 명칭 셀렉터
                market_el = self.driver.find_element(By.CSS_SELECTOR, 'a[href*="/market/"] span, [class*="MarketName"], [class*="StoreName"]')
                data['brand'] = market_el.text.strip()
            except:
                og_desc = soup.find("meta", property="og:description")
                if og_desc: data['brand'] = og_desc['content'].split(' ')[0]

            # 3. 가격
            try:
                price_text = self.driver.find_element(By.CSS_SELECTOR, 'span[class*="Price"], [class*="discount_price"]').text
                data['discounted_price'] = int(re.sub(r'[^0-9]', '', price_text))
            except: 
                # 실패 시 기존 page_text 정규식 백업
                page_text = self.driver.find_element(By.TAG_NAME, "body").text
                price_matches = re.findall(r'([\d,]+)원', page_text)
                if price_matches:
                    data['discounted_price'] = int(price_matches[0].replace(',', ''))

            # 4. 할인율 (discount_rate)
            try:
                price_container = self.driver.find_element(By.CLASS_NAME, "sc-ad5f1e6f-0")
                discount_rate_el = price_container.find_elements(By.CLASS_NAME, "color__pink30")
                data['discount_rate'] = discount_rate_el[0].text.replace('%', '').strip() if discount_rate_el else "0"
            except:
                # 백업: 전체 텍스트에서 % 앞에 있는 숫자 찾기
                rate_match = re.search(r'(\d+)%', self.driver.find_element(By.TAG_NAME, "body").text)
                if rate_match:
                    data['discount_rate'] = int(rate_match.group(1))

            # 2. 리뷰 점수 & 개수 (강력한 정규식 버전)
            try:
                page_text = self.driver.find_element(By.TAG_NAME, "body").text
                count_match = re.search(r'리뷰\s*([\d,]+)개', page_text)
                if count_match:
                    data['review_count'] = int(count_match.group(1).replace(',', ''))
                else:
                    data['review_count'] = 0
            
                score_match = re.search(r'([\d.]+)%가\s*만족한', page_text)
                if score_match:
                    raw_percent = float(score_match.group(1))
                    data['review_score'] = round(max(0, (raw_percent - 50) / 10), 2)
                else:
                    data['review_score'] = 0.0
            except:
                data['review_count'] = 0
                data['review_score'] = 0.0

            try:
                likes_container = self.driver.find_element(By.CLASS_NAME, "sc-45b21edb-3")
                likes_text = likes_container.find_element(By.CLASS_NAME, "color__pink30").text.strip()
                if '만' in likes_text:
                    data['product_likes'] = str(int(float(likes_text.replace('만', '')) * 10000))
                else:
                    data['product_likes'] = likes_text.replace(',', '')
            except:
                data['product_likes'] = "0"

           # 7. 오늘출발 이미지 판별 (언니가 준 주소 그대로 사용)
            try:
                # 페이지의 모든 이미지를 다 가져와서
                all_imgs = self.driver.find_elements(By.TAG_NAME, 'img')
                
                is_today = False
                for img in all_imgs:
                    src = img.get_attribute('src')
                    if src:
                        # 언니가 준 그 긴 주소의 핵심 부분만 포함되어 있는지 확인!
                        # 주소 전체를 다 넣어도 되고, 유니크한 뒷부분만 넣어도 돼.
                        if "today_delivery_compact.png" in src or "czM6Ly9pbWcuYS1ibHkuY29tL2RhdGEvZ29vZHMvZGVsaXZlcnktdHlwZS90b2RheV9kZWxpdmVyeV9jb21wYWN0LnBuZw" in src:
                            is_today = True
                            break
                
                data['is_direct_shipping'] = 1 if is_today else 0

            except Exception as e:
                print(f"❌ 배송 판별 오류: {e}")
                data['is_direct_shipping'] = 0
                
            return data

        except Exception as e:
            print(f"❌ Crawling Error: {e}")
            return {}

    def close(self):
        self.driver.quit()
        
def crawl_product_data(url, platform):
    print(f"🚀 Crawling {url} on {platform}...")
    
    # 1. 크롤러 결과물을 담을 바구니
    crawled_result = {}
    crawler = None

    try:
        # 2. 플랫폼별 크롤러 가동
        if platform == "musinsa":
            crawler = MusinsaPerfectScraper()
            crawled_result = crawler.run(url)
        elif platform == "zigzag":
            crawler = ZigzagDetailCrawler()
            crawled_result = crawler.crawl_detail(url)
        elif platform == "ably":
            crawler = AblyDetailCrawler()
            crawled_result = crawler.crawl_detail(url)
        else:
            print(f"⚠️ 지원하지 않는 플랫폼: {platform}")
            return {}

    except Exception as e:
        print(f"❌ 크롤러 물리적 실행 에러 ({platform}): {e}")
        import traceback
        traceback.print_exc() 
        return {}
    finally:
        if crawler:
            crawler.close()

    # 3. 데이터 정규화 (crawled_result에서 값을 꺼내서 정리)
    normalized_data = {}
    
    # [텍스트 필드]
    p_name = crawled_result.get("product_name", "Unknown")
    normalized_data["product_name"] = p_name
    normalized_data["product_img"] = crawled_result.get("product_img", "")
    normalized_data["platform"] = platform
    normalized_data["category"] = crawled_result.get("category", "Unknown")
    normalized_data["brand"] = crawled_result.get("brand", "Unknown")
    
    # [숫자 필드 변환 도우미 함수]
    def safe_int(val):
        if not val: return 0
        try: return int(re.sub(r'[^0-9]', '', str(val)))
        except: return 0

    def safe_float(val):
        if not val: return 0.0
        try: return float(re.sub(r'[^0-9.]', '', str(val)))
        except: return 0.0

    # 데이터 매핑
    normalized_data["discounted_price"] = safe_int(crawled_result.get("discounted_price"))
    normalized_data["free_shipping"] = safe_int(crawled_result.get("free_shipping", 0))
    normalized_data["discount_rate"] = safe_int(crawled_result.get("discount_rate"))
    normalized_data["review_score"] = safe_float(crawled_result.get("review_score"))
    normalized_data["review_count"] = safe_int(crawled_result.get("review_count"))
    
    # [좋아요 특별 처리] '만' 단위 포함
    likes = str(crawled_result.get("product_likes", "0"))
    if '만' in likes:
        likes = str(int(float(likes.replace('만', '')) * 10000))
    normalized_data["product_likes"] = safe_int(likes)
    
    normalized_data["is_direct_shipping"] = safe_int(crawled_result.get("is_direct_shipping", 0))
    
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

        '''
        if not result or p_name == "Unknown":
            return {"product_name": "Error", "details": "데이터를 가져오지 못했습니다."}
        ''' 

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
        
        '''
        # extract_features_from_url 함수 하단 수정
        if not result or result.get("product_name") == "Unknown":
            # 🚩 그냥 400 던지지 말고, 이유를 적어서 보내달라고 해!
            return {"error": "Crawling failed", "debug_data": result}
        '''
        # 최종 결과 반환
        return result   

    except Exception as e:
        # ❌ 단순히 e만 찍지 말고, 어디서 터졌는지 전체 경로를 다 찍어보자!
        print("--- 에러 상세 경로 시작 ---")
        print(traceback.format_exc()) 
        print("--- 에러 상세 경로 끝 ---")
        return {"product_name": "Error", "details": str(e)}