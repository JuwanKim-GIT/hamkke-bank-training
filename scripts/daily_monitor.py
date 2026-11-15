import json, os, sys, urllib.request, urllib.error
import smtplib, ssl
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone

BASE = os.getenv('SUPABASE_URL', '').rstrip('/')
KEY = os.getenv('SUPABASE_PUBLISHABLE_KEY', '')
EMAIL = os.getenv('SUPABASE_MONITOR_EMAIL', '')
PASSWORD = os.getenv('SUPABASE_MONITOR_PASSWORD', '')
SMTP_PASSWORD = os.getenv('NAVER_SMTP_PASSWORD', '')
MAIL_ADDRESS = 'youwany@naver.com'
KST = timezone(timedelta(hours=9))


def post(url, data, headers=None):
    payload = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(url, payload, {'Content-Type': 'application/json', **(headers or {})}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=25) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'HTTP {e.code} from {url.split("/")[-1]}') from e


def send_email(subject, body):
    if not SMTP_PASSWORD:
        raise RuntimeError('Missing NAVER_SMTP_PASSWORD GitHub Actions secret')
    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = MAIL_ADDRESS
    message['To'] = MAIL_ADDRESS
    message.set_content(body)
    with smtplib.SMTP_SSL('smtp.naver.com', 465, context=ssl.create_default_context(), timeout=30) as smtp:
        smtp.login(MAIL_ADDRESS, SMTP_PASSWORD)
        smtp.send_message(message)


def append_summary(report):
    path = os.getenv('GITHUB_STEP_SUMMARY')
    if path:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(report + '\n')


def main():
    if not all([BASE, KEY, EMAIL, PASSWORD]):
        raise RuntimeError('Missing required Supabase GitHub Actions secrets')
    auth = post(BASE + '/auth/v1/token?grant_type=password', {'email': EMAIL, 'password': PASSWORD}, {'apikey': KEY})
    token = auth.get('access_token')
    if not token:
        raise RuntimeError('Authentication did not return an access token')
    result = post(BASE + '/functions/v1/hamkke-v2-list-sessions', {}, {'apikey': KEY, 'Authorization': 'Bearer ' + token})
    if result.get('success') is False or not isinstance(result.get('sessions'), list):
        raise RuntimeError('Session API returned an unexpected response')
    sessions = result['sessions']
    today = datetime.now(KST).date()
    yesterday = today - timedelta(days=1)
    matching = []
    for s in sessions:
        started = s.get('started_at')
        if not started:
            continue
        try:
            dt = datetime.fromisoformat(started.replace('Z', '+00:00')).astimezone(KST)
        except (ValueError, TypeError):
            continue
        if dt.date() == yesterday:
            matching.append(s)
    counts = [s.get('student_count') for s in matching]
    known = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in counts)
    students = sum(int(v) for v in counts) if known else None
    lines = [
        '# 함께은행 일일 운영 점검',
        f'- 확인 시각(KST): {datetime.now(KST):%Y-%m-%d %H:%M}',
        '- Supabase API: 정상 응답',
        f'- 전날({yesterday}) 시작한 교육 세션: {len(matching)}건',
        f'- 전날 세션의 교육생 수 합계: {students}명' if students is not None else '- 전날 세션의 교육생 수 합계: 확인 불가 (API 제공값 부족)',
        '- 참고: 세션별 참여 인원 합계이며 동일인이 여러 세션에 참여하면 중복 집계될 수 있습니다.',
    ]
    report = '\n'.join(lines)
    print(report)
    append_summary(report)
    send_email(f'[함께은행] 일일 점검 정상 - {today}', report)
    print('네이버 이메일 발송 완료')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        error = f'함께은행 점검 실패: {exc}'
        print(error, file=sys.stderr)
        append_summary(f'## 함께은행 일일 운영 점검 실패\n- 시각(KST): {datetime.now(KST):%Y-%m-%d %H:%M}\n- 오류: {exc}')
        try:
            send_email(f'[함께은행] 일일 점검 실패 - {datetime.now(KST):%Y-%m-%d}', error)
            print('실패 알림 이메일 발송 완료')
        except Exception as mail_exc:
            print(f'실패 알림 이메일 발송 실패: {mail_exc}', file=sys.stderr)
        sys.exit(1)
