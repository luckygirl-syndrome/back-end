# app/chat/logic/user_survey.py

def determine_mode(answers: list) -> str:
    """
    설문 답변(리스트 형태)을 분석하여 BRAKE 또는 DECIDER 모드를 결정합니다.
    AI_chatbot에서 정제된 로직을 사용합니다.
    """
    # 리스트 형태의 답변을 딕셔너리로 변환
    ans_dict = {a['q_id']: a['answer_id'] for a in answers if 'answer_id' in a}
    
    # 기본값 설정 (답변이 누락된 경우를 대비)
    q1 = ans_dict.get(1, 1)
    q2 = ans_dict.get(2, 1)
    q3 = ans_dict.get(3, 1)

    from ..constants import SURVEY_SCORE_TABLE
    
    # 총점 계산
    b_score = SURVEY_SCORE_TABLE["q1"].get(q1, (0,0))[0] + \
              SURVEY_SCORE_TABLE["q2"].get(q2, (0,0))[0] + \
              SURVEY_SCORE_TABLE["q3"].get(q3, (0,0))[0]
    d_score = SURVEY_SCORE_TABLE["q1"].get(q1, (0,0))[1] + \
              SURVEY_SCORE_TABLE["q2"].get(q2, (0,0))[1] + \
              SURVEY_SCORE_TABLE["q3"].get(q3, (0,0))[1]

    # 최종 모드 결정
    if b_score > d_score:
        return "BRAKE"
    else:
        return "DECIDER"
