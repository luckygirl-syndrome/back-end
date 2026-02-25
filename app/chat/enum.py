class ChatStatus:
    ANALYZING = "ANALYZING"   # 1. AI가 분석 중
    PENDING = "PENDING"       # 2. 대화 중 (가장 활발한 상태)
    FINISHED = "FINISHED"     # 3. 대화 종료 (유저가 Exit 버튼 누름 / 결정 전)
    PURCHASED = "PURCHASED"   # 4. 구매 완료 (구매 확정 버튼 누름)
    ABANDONED = "ABANDONED"   # 5. 구매 포기 (안 살래요 버튼 누름)