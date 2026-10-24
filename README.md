# ProjectHelper programming

고등학교 Python 프로젝트를 위한 대화형 학습 도우미입니다.

공개 화면: https://miaelang.github.io/ProjectHelper_programming/

## 구조

GitHub Pages → Cloudflare HTTPS 터널 → 교사 맥북의 Flask/Waitress API → SQLite와 Ollama(gemma3:12b).
GitHub Pages는 화면 파일만 제공합니다. 로그인, 기록 저장, AI 답변은 맥북 서버가 담당합니다. 맥북과 Ollama, API, 터널이 켜져 있어야 합니다.

## 실행

Python 3.11 이상 환경에서 `server/requirements.txt`를 설치합니다. `PROJECTHELPER_DATA`를 비공개 데이터 폴더로 지정하고 `python server/server.py`를 실행합니다. API는 127.0.0.1:8877에 바인딩됩니다. 교사 계정은 로컬에서 생성해야 하며 인터넷 회원가입은 없습니다.

공식 cloudflared 프로그램으로 `cloudflared tunnel --url http://127.0.0.1:8877 --no-autoupdate`를 실행합니다. 표시된 HTTPS 주소를 `config.json`의 `api_base`에 저장해 커밋합니다. GitHub Settings → Pages에서 main 브랜치의 /(root)를 선택합니다.

무료 Quick Tunnel 주소는 재실행할 때 바뀝니다. 그때마다 config.json 업데이트가 필요합니다. 이 구성은 상시 가용성을 보장하는 서비스가 아닌 수업 시범운영용입니다. 컴퓨터를 잠자기 상태로 두거나 인터넷 연결이 바뀌면 접속이 끊길 수 있습니다.

## 데이터와 학교 검토

DB·비밀번호·계정 발급표·학생 대화는 GitHub에 업로드하지 않습니다. 비밀번호는 개별 salt를 사용한 scrypt 검증값으로 저장합니다. 학생은 자기 기록만, 교사는 담당 학생 기록만 열람합니다. 임시 비밀번호는 첫 로그인에 변경하며 세션은 30분 미사용 또는 8시간 후 만료됩니다.

Cloudflare는 로그인 및 대화 요청을 중계하고 HTTPS를 종료합니다. '데이터가 외부를 거치지 않는다'고 안내하면 안 됩니다. 화면 제공에는 GitHub Pages가 사용됩니다. 외부 AI API는 사용하지 않습니다.

학교/에듀집 승인 및 연구 참여 절차는 배포와 별개입니다. 학교 검토 전에 실제 학생 자료로 운영하지 마세요. 수집 항목, 중계 서비스, 운영자 연락처, 보관 기간, 삭제·백업 절차를 학교 서류와 안내문에 반영해야 합니다. 연구 동의 여부는 수업 이용과 구분하며 내보낸 대화에 포함된 개인정보를 별도로 검토해야 합니다. 보관 예정일 설정은 자동 삭제가 아닙니다.

## 검증 범위

가상 계정으로 비밀번호 변경, 역할·학생별 접근 차단, Origin 제한, 중복 질문 방지, 로그아웃, HTTPS 로그인 및 실제 AI 응답, 재로그인 후 기록 복원을 확인했습니다. 25명 동시 사용과 학교망 접근은 현장에서 추가 검증이 필요합니다. 한 번에 한 AI 요청을 처리하며 대기 순서를 표시합니다.
