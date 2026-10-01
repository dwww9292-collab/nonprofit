# 08. 배포 — 사내 맥 서버 운영 가이드

## 0. 왜 사내 서버인가 (호스팅 방식 결정 근거)

이 시스템의 DB에는 비영리단체 **대표자 성명·전화번호 약 9,000건 이상**이 들어 있다
(행안부 비영리민간단체 등록현황 원본에 포함된 항목). 이는 개인정보보호법상 개인정보이고,
우리가 수집 주체가 아니라 공개데이터를 가공해 보유하는 형태다.

| 방식 | 판단 |
|---|---|
| **사내 서버 + Docker Compose** | **채택.** 개인정보가 사내망을 벗어나지 않음. 위탁처리 계약·국외이전 이슈 없음. 지금 구성 그대로 복사하면 끝 |
| Railway / Render / Fly.io | 비권장. DB가 해외 리전에 올라가면 개인정보 국외이전 고지 의무가 생기고, 무료 등급은 볼륨이 날아갈 수 있음 |
| AWS / NCP (국내 리전) | 외부 접속이 상시 필요해지면 그때 검토. VPC·보안그룹·백업을 직접 설계해야 하므로 지금 단계에선 과투자 |
| Vercel | 불가. 프론트 정적 호스팅 전용이라 PostgreSQL·배치 적재를 올릴 수 없음 |

결론: **맥을 사내 서버로 쓰고, 외부에서 봐야 하면 포트 개방 대신 Tailscale 을 쓴다.**

## 1. 필요 사양 — 맥이면 거의 무조건 충분하다

실측 기준(리드 23,228건, 기재부+행안부 전량):

| 항목 | 실사용 | 권장 최소 |
|---|---|---|
| CPU | 적재 중 2코어 100%, 평시 거의 0 | 2코어 |
| RAM | 컨테이너 3개 합 약 1.2GB | 4GB (여유 8GB) |
| 디스크 | DB 약 180MB + 이미지 약 2.5GB | 20GB 여유 |
| 네트워크 | 사내망만 | — |

Apple Silicon(M1 이상)·8GB 이상이면 넉넉하다. `postgres:16-alpine`, `python:3.12-slim`,
`node:22-slim`, `nginx:alpine` 모두 arm64 이미지가 있어 Rosetta 없이 그대로 돈다.

사양 확인:

```bash
sw_vers                                             # macOS 버전
system_profiler SPHardwareDataType | grep -E "Chip|Memory|Model Name"
df -h /                                             # 디스크 여유
```

## 2. 설치

### 2-1. Docker Desktop

<https://www.docker.com/products/docker-desktop/> → Apple Silicon 버전.

> **라이선스 주의**: Docker Desktop 은 종업원 250명 이상 **또는** 연매출 1,000만 달러 이상
> 기업의 상업적 사용 시 유료 구독이 필요하다. 해당되면 Docker Desktop 대신 `colima`
> (`brew install colima docker docker-compose && colima start --cpu 2 --memory 4`) 를 쓰면
> 같은 compose 명령이 그대로 동작한다.

설정 → General → **Start Docker Desktop when you sign in** 체크.

### 2-2. 저장소와 .env

```bash
cd ~
git clone https://github.com/dwww9292-collab/nonprofit.git
cd nonprofit
cp .env.example .env
```

`.env` 를 열어 값을 채운다. 비밀값 2개는 반드시 새로 생성한다:

```bash
python3 -c "import secrets; print('JWT_SECRET=' + secrets.token_urlsafe(48))"
python3 -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(24))"
```

사내망 접속용으로 아래 3개를 추가한다 (맥의 사설 IP는 `ipconfig getifaddr en0` 로 확인):

```dotenv
BIND_ADDR=0.0.0.0
HTTP_PORT=3000
CORS_ORIGINS=http://192.168.0.50:3000
```

> `.env` 는 `.gitignore` 에 있다. **절대 커밋하지 않는다.** 서버 이관 시에는 git 이 아니라
> 1Password·사내 금고 등으로 따로 전달한다.

### 2-3. 기동

```bash
docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --build
docker compose ps          # 3개 모두 running / backend healthy 확인
```

`docker-compose.server.yml` 이 하는 일은 하나다 — `restart: always` 로 크래시·재부팅 후
자동 복구를 켠다.

**공개 범위는 override 파일이 아니라 `.env` 의 `BIND_ADDR` 로 제어한다.** compose 는
override 파일의 `ports` 를 교체가 아니라 '합치기'로 처리해서, override 에 `0.0.0.0:3000` 을
적으면 base 의 `127.0.0.1:3000` 과 **함께** 두 번 바인딩되어 포트 충돌로 기동이 실패한다.
그래서 base 쪽 포트를 `${BIND_ADDR:-127.0.0.1}:${HTTP_PORT:-3000}:80` 으로 두었다.
변수를 안 주면 로컬 전용이 기본값이다.

백엔드(8000)·DB(5432) 포트는 어느 경우에도 열리지 않는다. nginx 가 compose 내부
네트워크로 `/api/` 를 프록시하므로 열 이유가 없다.

설정이 의도대로 합쳐졌는지는 기동 전에 확인할 수 있다:

```bash
docker compose -f docker-compose.yml -f docker-compose.server.yml config | grep -A4 "frontend:"
# host_ip 가 0.0.0.0 하나만 나와야 한다
```

사내 다른 PC에서 `http://192.168.0.50:3000` 으로 접속된다.

## 3. 맥을 24시간 서버로 만들기

노트북 기본 설정으로는 뚜껑을 덮거나 일정 시간 뒤 잠들어 서비스가 끊긴다.

```bash
# 잠자기 끄기 (디스플레이만 10분 후 꺼짐)
sudo pmset -a sleep 0 disksleep 0 displaysleep 10

# 뚜껑 닫아도 안 자게 (전원 연결 상태 필수)
sudo pmset -a disablesleep 1

# 정전 복구 후 자동 부팅
sudo systemsetup -setrestartpowerfailure on

# 현재 설정 확인
pmset -g
```

**자동 로그인**: Docker Desktop 은 GUI 로그인 세션에서만 뜬다. 재부팅 후 사람이 없어도
서비스가 올라와야 하므로 시스템 설정 → 사용자 및 그룹 → **자동 로그인**을 켠다.
단 자동 로그인은 FileVault 와 함께 쓸 수 없다 — 물리적으로 통제되는 사무실에 두고,
화면 보호기 암호를 짧게 설정하는 쪽으로 보완한다. (colima 를 쓰면 이 제약이 없다.)

추가 권장:
- 시스템 설정 → 네트워크 → **고정 IP** 또는 공유기에서 DHCP 예약 (IP가 바뀌면 북마크가 깨진다)
- 시스템 설정 → 소프트웨어 업데이트 → **자동 재시작 업데이트 끄기** (업무시간 중 재부팅 방지)
- 전원 → 무정전 전원장치(UPS) 있으면 연결

## 4. 외부(재택·외근) 접속 — Tailscale 권장

공유기 포트포워딩은 하지 않는다. 로그인이 HTTP 평문이고, 개인정보 DB가 인터넷에 직접
노출된다.

```bash
brew install --cask tailscale     # 맥 서버와 접속할 기기 양쪽에 설치
```

Tailscale 설치 후 서버 맥에서:

```bash
tailscale ip -4                   # 100.x.y.z 형태 주소
sudo tailscale cert <머신이름>.<테일넷>.ts.net   # HTTPS 인증서 (선택)
sudo tailscale serve --bg --https=443 http://127.0.0.1:3000
```

이러면 테일넷에 가입된 기기에서만 `https://<머신이름>.<테일넷>.ts.net` 으로 HTTPS 접속된다.
이 경우 `.env` 의 `BIND_ADDR` 은 `127.0.0.1` 로 되돌려 사내망 개방도 닫을 수 있다.

## 5. 데이터 백업 — 반드시 설정할 것

`pgdata` 볼륨 하나에 전부 들어 있다. 맥 디스크가 죽으면 23,000건과 영업 이력이 함께 사라진다.

### 수동 백업

```bash
./ops/backup.sh
# 백업 완료: ./backups/npo-20261001-031000.sql.gz (4,210 KB)
```

### 자동 백업 (매일 03:10)

```bash
mkdir -p backups                                   # launchd 로그 경로가 먼저 있어야 한다
sed -i '' "s#__REPO__#$HOME/nonprofit#g" ops/com.npo-sales.backup.plist
cp ops/com.npo-sales.backup.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.npo-sales.backup.plist

launchctl start com.npo-sales.backup               # 즉시 1회 실행해 확인
cat backups/backup.log
```

Time Machine 도 함께 켜되, **백업 파일에 개인정보가 들어 있으므로** 저장 위치는 사내
통제 범위(사내 NAS·사내 보관 외장디스크)여야 한다. iCloud/Dropbox 동기화 폴더는 안 된다.
외부 디스크로 보내려면:

```bash
BACKUP_DIR=/Volumes/사내백업/npo KEEP_DAYS=90 ./ops/backup.sh
```

### 복원

```bash
./ops/restore.sh backups/npo-20261001-031000.sql.gz
# 대상 DB 이름을 직접 입력해야 진행된다 (오조작 방지)
```

## 6. 일상 운영 명령

```bash
# 중지 (데이터 유지)
docker compose down

# ⚠️ 절대 쓰지 말 것 — pgdata 볼륨까지 삭제되어 전체 데이터가 사라진다
# docker compose down -v

# 코드 업데이트 반영
git pull origin main
docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --build

# 로그
docker compose logs -f backend
docker compose logs --tail=100 frontend

# 리드 건수 확인
docker compose exec db psql -U "$POSTGRES_USER" -d npo_sales \
  -c "SELECT count(*) FROM leads WHERE deleted_at IS NULL;"
```

### 분기별 데이터 갱신

기재부 지정누계는 분기마다, 행안부 등록현황은 월마다 갱신된다
(출처·경로는 `docs/04-data-sources.md`).

```bash
mkdir -p data
# 새 파일을 data/ 에 넣고 (data/ 는 .gitignore 처리되어 커밋되지 않는다)
docker compose cp data backend:/data
docker compose exec backend python -m scripts.ingest auto /data
```

### 점수 재계산

스코어링에는 **오늘 날짜 기준 항목**이 있다 — 신규지정 180일, 신규설립 90일,
수집 신선도 7/30/90일(`docs/03-scoring.md`). 점수는 DB에 저장되고 적재·병합 시점에만
다시 계산되므로, 시간이 지나면 실제 등급과 어긋난다. 월 1회 전체 재계산을 권한다.

```bash
docker compose exec backend python -c "
from app.core.db import SessionLocal
from app.services.scoring import rescore_all
db = SessionLocal()
print('재계산:', rescore_all(db), '건')
db.commit()
"
```

관리자로 로그인해 **설정** 화면의 **전체 재계산 실행** 버튼으로도 같은 작업을 할 수 있다.

## 7. pg_trgm 한글 판정 점검 (기존 볼륨이라면 반드시)

유사 명칭 중복의심(중복판정 4단계)은 pg_trgm 의 `similarity()` 에 기댄다. pg_trgm 은
`LC_CTYPE` 으로 무엇이 '문자'인지 판정하는데, 로케일이 `C` 이면 한글이 문자로 분류되지
않아 트라이그램이 하나도 만들어지지 않는다. 그러면 오류 없이 **조용히** 유사도가 늘 0이
되고, 중복의심 배지가 한 번도 뜨지 않는다.

`postgres:16-alpine` 은 기본 로케일이 `C` 라서 이 상태로 초기화됐을 수 있다. 확인:

```bash
docker compose exec db psql -U "$POSTGRES_USER" -d npo_sales   -c "SELECT similarity('예시복지재단','예시복지재단') AS must_be_1;"
```

- `1` 이면 정상이다.
- `0` 이면 중복의심이 동작하지 않는 상태다.

`0` 일 때 고치려면 클러스터를 다시 만들어야 한다(로케일은 생성 후 바꿀 수 없다).
`docker-compose.yml` 에 `POSTGRES_INITDB_ARGS: "--lc-ctype=C.UTF-8"` 를 넣어 두었으므로,
백업 → 볼륨 삭제 → 재기동 → 복원 순서로 처리한다.

```bash
./ops/backup.sh                      # 1) 먼저 백업 (반드시)
docker compose down -v               # 2) 볼륨 삭제 — 백업을 확인한 뒤에만
docker compose up -d --build         # 3) 새 로케일로 초기화 + 마이그레이션
docker compose exec db psql -U "$POSTGRES_USER" -d npo_sales   -c "SELECT similarity('예시복지재단','예시복지재단');"   # 4) 1 인지 확인
./ops/restore.sh backups/npo-<가장최근>.sql.gz            # 5) 복원
```

> 데이터 전체가 걸린 작업이다. 2번 이전에 백업 파일이 실제로 존재하고 크기가 정상인지
> 눈으로 확인한다. 중복의심 기능을 당장 쓰지 않는다면 다음 점검 때로 미뤄도 된다.

## 8. 점검 체크리스트

운영 시작 전 한 번 확인한다.

- [ ] `git status --short` 에 `.env`, `data/`, `backups/`, `*.xls*` 가 **보이지 않는다**
- [ ] `.env` 의 `JWT_SECRET`·`POSTGRES_PASSWORD`·`ADMIN_PASSWORD` 가 `.env.example` 의 예시값과 다르다
- [ ] 초기 관리자 비밀번호를 로그인 후 변경했다
- [ ] `pmset -g` 에서 `sleep 0`, `SleepDisabled 1` 이다
- [ ] 맥을 재부팅해도 사내 다른 PC에서 접속된다
- [ ] `./ops/backup.sh` 가 성공하고, `./ops/restore.sh` 로 복원이 된다 (테스트 1회 필수)
- [ ] `docker compose exec db psql ... -c "select count(*) from leads"` 가 기대 건수를 돌려준다
- [ ] `similarity('예시복지재단','예시복지재단')` 가 `1` 이다 (7절)
