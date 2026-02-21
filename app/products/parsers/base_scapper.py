import time
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class BaseScraper:
    def __init__(self):
        self.chrome_options = Options()
        
        # 1. 기본 배포 설정
        self.chrome_options.add_argument('--headless=new') # 최신 헤드리스 모드 사용
        self.chrome_options.add_argument('--no-sandbox')
        self.chrome_options.add_argument('--disable-dev-shm-usage')
        self.chrome_options.add_argument('--disable-gpu')
        
        # 2. 화면 크기 (지그재그/에이블리 찜수 로딩 방지)
        self.chrome_options.add_argument('--window-size=1920,1080')
        
        # 3. 언어 및 지역 설정 (서버 IP여도 한국인 척 하기)
        self.chrome_options.add_argument('--lang=ko_KR')
        self.chrome_options.add_argument('--disable-blink-features=AutomationControlled') # 봇 인식 방지
        
        # 4. 강력한 유저 에이전트 (아이폰 17 최신 버전)
        user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
        self.chrome_options.add_argument(f'user-agent={user_agent}')

        # 5. 자동화 흔적 지우는 옵션 추가
        self.chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.chrome_options.add_experimental_option('useAutomationExtension', False)

        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=self.chrome_options)

        # 🚩 [치트키] 브라우저 내부 자바스크립트 변수 조작
        # navigator.webdriver를 false로 만들어서 셀레니움인걸 완벽히 숨김
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                window.chrome = {
                    runtime: {}
                };
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['ko-KR', 'ko']
                });
            """
        })
        
        self.driver.implicitly_wait(10)

    def close(self):
        if self.driver:
            self.driver.quit()