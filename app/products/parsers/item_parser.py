import os, json, re, time, socket
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from bs4 import BeautifulSoup
import logging

# 🚩 [추가] selenium-wire의 시끄러운 네트워크 로그(INFO)를 차단함
logging.getLogger('seleniumwire').setLevel(logging.WARNING)
# hpack 등의 하위 라이브러리 로그도 조용히 시킴
logging.getLogger('hpack').setLevel(logging.WARNING)

# 🚩 [수정] selenium 대신 seleniumwire를 임포트해야 프록시 옵션을 인식해!
from seleniumwire import webdriver 
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
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
        
        # 🚩 [추가] 이미지 로딩 차단으로 속도 최적화
        prefs = {"profile.managed_default_content_settings.images": 2}
        chrome_options.add_experimental_option("prefs", prefs)
        
        selenium_url = os.environ.get("SELENIUM_URL", "http://selenium:4444/wd/hub")
        self.driver = webdriver.Remote(command_executor=selenium_url, options=chrome_options)

    def run(self, url):
        # 🛡️ 1. try 문 밖에서 가장 먼저 빈 바구니를 만듭니다. (에러 방지용)
        self.result = {
            'product_img': "", 'profile_img': "", 'product_name': "Unknown", 
            'brand': "Unknown", 'category': "Unknown", 'discounted_price': 0,
            'review_score': "0", 'review_count': "0", 'discount_rate': "0",
            'free_shipping': 1,
            'is_direct_shipping': 0, 'product_likes': "0"
        }

        try:
            print("📍 [Step 1] 브라우저 실행 중...")
            self.driver.get(url)
            print("📍 [Step 2] 페이지 접속 완료, 대기 중...")
            wait = WebDriverWait(self.driver, 15)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

            # 🚩 [리뷰 탈출 필살기] 화면을 중간까지 슥- 내려서 리뷰 로딩시키기
            self.driver.execute_script("window.scrollTo(0, 1500);") 
            time.sleep(0.5) # 1.5 -> 0.5로 단축
            
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
  
            # [이미지] 메타태그에서 먼저 쓱싹
            try:
                self.result['product_img'] = self.driver.find_element(By.XPATH, '//meta[@property="og:image"]').get_attribute('content')
            except: pass

            # [핵심 데이터] BeautifulSoup 대신 Selenium의 '텍스트'를 직접 가져오기 (훨씬 강력함!)
            # 클래스명이 바뀌어도 대응하도록 CSS Selector를 유연하게 짰어.
            selectors = {
                'product_name': "span[class*='GoodsName'], h2[class*='title'], .product_title",
                'brand': "span[class*='Brand__BrandName'], .brand_name",
                'discounted_price': "span[class*='Price__CalculatedPrice'], .total_price",
                'discount_rate': "span[class*='Price__DiscountRate'], .discount_percent",
                'product_likes': "div[class*='Like__Container'] span, .like_count, [class*='CommonLike']",
            }

            # 1. 특정 배송 정보 컨테이너 먼저 확인 (Selenium 활용)
            try:
                # 무신사 플러스배송/도착보장 영역 셀렉터들
                delivery_selectors = [
                    "div[class*='PlusDeliveryArrivalInfo']",
                    "div[class*='DeliveryInfo__Arrival']",
                    "div[class*='ShippingInfo']",
                    ".goods_delivery_info"
                ]
                
                delivery_text = ""
                for sel in delivery_selectors:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, sel)
                    if elements:
                        delivery_text += " ".join([el.text for el in elements])

                # 2. 텍스트 키워드 매칭
                keywords = ["플러스배송", "도착 보장", "오늘출발", "내일 도착", "22:00 전 결제"]
                if any(word in delivery_text for word in keywords):
                    self.result['is_direct_shipping'] = 1
                else:
                    # 백업: 전체 바디 텍스트에서 키워드 한 번 더 검색
                    body_text = self.driver.find_element(By.TAG_NAME, "body").text
                    if any(word in body_text[:3000] for word in keywords): # 상단 3000자 이내
                        self.result['is_direct_shipping'] = 1
                    else:
                        self.result['is_direct_shipping'] = 0
            except:
                self.result['is_direct_shipping'] = 0

            for key, selector in selectors.items():
                try:
                    # 요소를 하나만 찾는 게 아니라 여러 개 시도해보고 첫 번째 걸로 가져오기
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        self.result[key] = elements[0].text.strip() 
                except:
                    continue

            # 🚩 [가격 데이터 정제] - "29,900원" -> "29900"으로 미리 바꿔두기
            if self.result['discounted_price']:
                raw_price = str(self.result['discounted_price'])
                clean_price = re.sub(r'[^0-9]', '', raw_price)
                self.result['discounted_price'] = int(clean_price) if clean_price else 0

            # [카테고리]
            try:
                cats = self.driver.find_elements(By.CSS_SELECTOR, "div[class*='Category__Wrap'] a, .breadcrumb a")
                if cats:
                    self.result['category'] = " > ".join([c.text.strip() for c in cats])
            except: pass

            # 🚩 [리뷰 Summary 영역 수정 버전]
            try:
                review_area = self.driver.find_element(By.CSS_SELECTOR, "div[class*='ReviewSummary']")
                spans = review_area.find_elements(By.TAG_NAME, "span")
                
                for s in spans:
                    text = s.text.strip()
        
                    # 1. '4.8' 또는 '5' 같은 숫자가 보이면 점수로 저장
                    # 정수(5) 혹은 소수점 한 자리(4.8) 모두 매칭 가능하도록 수정
                    if re.match(r'^\d(\.\d)?$', text):
                        self.result['review_score'] = text
            
                    # 2. '후기'라는 글자가 보이면 숫자만 발라내서 개수로 저장
                    elif '후기' in text:
                        # 후기 (1,234) 같은 경우를 대비해 쉼표(,)도 제거하는 게 안전해!
                        clean_count = re.sub(r'[^0-9]', '', text)
                        self.result['review_count'] = clean_count
            
                print(f"✅ 리뷰 데이터 확인: 점수({self.result.get('review_score', '0')}), 개수({self.result.get('review_count', '0')})")
            except Exception as e:
                print(f"❌ 리뷰 영역 크롤링 중 오류: {e}")

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
        self.chrome_options.add_argument('--disable-gpu')
        self.chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        
        # 🚩 [추가] 이미지 로딩 차단
        prefs = {"profile.managed_default_content_settings.images": 2}
        self.chrome_options.add_experimental_option("prefs", prefs)
        
        selenium_url = os.environ.get("SELENIUM_URL", "http://selenium:4444/wd/hub")
        self.driver = webdriver.Remote(command_executor=selenium_url, options=self.chrome_options)

    def _expand_product_info(self):
        try:
            more_button = WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located((By.XPATH, "//button[contains(., '상품정보 더 보기')]"))
            )
            self.driver.execute_script("arguments[0].click();", more_button)
            time.sleep(0.5) # 2 -> 0.5로 단축
        except Exception:
            pass

    def _safe_get_text(self, soup, selector):
        element = soup.select_one(selector)
        return element.get_text(strip=True) if element else None

    def crawl_detail(self, url):
        self.driver.get(url)
        time.sleep(1) # 3 -> 1로 단축
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
        # 1. 프록시 정보 설정
        proxy_id = "8a4a020f0b6a91a4299c"
        proxy_pw = "c9f06f1bee8caf88"
        proxy_host = "gw.dataimpulse.com"
        proxy_port = "823"

        try:
            host_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            host_ip = "127.0.0.1"

        proxy_options = {
            'addr': host_ip,
            'proxy': {
                'http': f'http://{proxy_id}:{proxy_pw}@{proxy_host}:{proxy_port}',
                'https': f'http://{proxy_id}:{proxy_pw}@{proxy_host}:{proxy_port}',
                'no_proxy': 'localhost,127.0.0.1'
            }
        }

        self.chrome_options = Options()
        # 🚩 데이터 아끼기용 이미지 차단 (이게 문제면 2를 1로 바꾸거나 이 블록을 삭제해!)
        prefs = {"profile.managed_default_content_settings.images": 2}
        self.chrome_options.add_experimental_option("prefs", prefs)

        # 언니가 원래 쓰던 우회 설정 그대로!
        self.chrome_options.add_argument('--headless')
        self.chrome_options.add_argument('--no-sandbox')
        self.chrome_options.add_argument('--disable-dev-shm-usage')
        self.chrome_options.add_argument('--disable-gpu')
        self.chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        self.chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.chrome_options.add_experimental_option('useAutomationExtension', False)
        self.chrome_options.add_argument("user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")

        # 🚩 [수정 포인트] seleniumwire_options만 추가!
        selenium_url = os.environ.get("SELENIUM_URL", "http://selenium:4444/wd/hub")
        self.driver = webdriver.Remote(
            command_executor=selenium_url, 
            options=self.chrome_options,
            seleniumwire_options=proxy_options # 프록시 주입
        )
        
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

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
            self.driver.get(url)
            # 1. 페이지 로딩 대기
            wait = WebDriverWait(self.driver, 10)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

            # 🚀 [핵심] 3단계 스크롤 로직 (리뷰/찜수가 로딩될 기회를 줌)
            for offset in [800, 1600]: 
                self.driver.execute_script(f"window.scrollTo(0, {offset});")
                time.sleep(0.5) # 1.5 -> 0.5로 단축
            
            # 다시 맨 위로 살짝 올려서 상단 정보도 놓치지 않게 함
            self.driver.execute_script("window.scrollTo(0, 500);")
            time.sleep(0.2) # 1.0 -> 0.2로 단축

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
    normalized_data["free_shipping"] = data.get("free_shipping", 0)

    dr = data.get("discount_rate", "0")
    if isinstance(dr, str): dr = re.sub(r'[^0-9]', '', dr)
    normalized_data["discount_rate"] = int(dr) if dr else 0
    
    rs = data.get("review_score", "0")
    if isinstance(rs, str): rs = re.sub(r'[^0-9.]', '', rs)
    normalized_data["review_score"] = float(rs) if rs else 0.0
    
    rc = data.get("review_count", "0")
    if isinstance(rc, str): rc = re.sub(r'[^0-9]', '', rc)
    normalized_data["review_count"] = int(rc) if rc else 0
    
    likes = str(data.get("product_likes", "0"))
    if '만' in likes:
        # 소수점(.)은 남겨두고 '만'만 지운 뒤 계산해야 2.2만이 22000이 됨!
        val = re.sub(r'[^0-9.]', '', likes.replace('만', ''))
        likes = str(int(float(val) * 10000)) if val else "0"
    elif '천' in likes:
        val = re.sub(r'[^0-9.]', '', likes.replace('천', ''))
        likes = str(int(float(val) * 1000)) if val else "0"
    
    # 마지막에 숫자가 아닌 찌꺼기들 제거
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

        # 최종 결과 반환
        return result

    except Exception as e:
        # ❌ 단순히 e만 찍지 말고, 어디서 터졌는지 전체 경로를 다 찍어보자!
        print("--- 에러 상세 경로 시작 ---")
        print(traceback.format_exc()) 
        print("--- 에러 상세 경로 끝 ---")
        return {"product_name": "Error", "details": str(e)}