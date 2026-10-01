# 09. 배포 — AWS 외부 공개 (Lightsail)

사내망 밖(재택·외근·거래처)에서도 봐야 할 때 쓴다. 사내망에서만 쓸 거면
`docs/08-deploy.md`(사내 서버) 쪽이 더 싸고 간단하다.

## 0. Vercel 로는 안 된다

| 필요한 것 | Vercel |
|---|---|
| PostgreSQL + pg_trgm | 없음 |
| 상시 구동 FastAPI | 서버리스 함수뿐 |
| 25MB 엑셀 127,000행 적재 (46초) | 함수 실행시간 제한에 걸림 |
| 영속 볼륨 | 없음 |

프론트엔드만 올릴 수는 있지만 DB·API 를 어차피 따로 둬야 해서 관리 지점만 늘어난다.
GitHub Pages 도 같은 이유로 불가하다.

## 1. 사양 — 실측 기준

가장 무거운 작업은 NSM 고객 마스터 동기화다. 실측값:

| 작업 | 최대 메모리 | 소요 |
|---|---|---|
| NSM 동기화 (126,914건 × 리드 23,228건) | **521 MB** | 46초 |
| 행안부 적재 (14,055행 .xls) | 약 300 MB | 98초 |
| 평시 (조회만) | 거의 0 | — |

컨테이너 합계 상주분(PostgreSQL 약 300MB + uvicorn 약 150MB + nginx·Caddy 약 30MB)에
적재 피크를 더하면 **약 1.2GB** 가 최대치다.

| 인스턴스 | 판단 |
|---|---|
| 1GB | 부족. 적재 중 OOM 으로 컨테이너가 죽는다 |
| **2GB / 2vCPU / 60GB** | **최소 권장.** 적재 때 여유가 많지는 않다 |
| 4GB / 2vCPU / 80GB | 넉넉하다. 적재를 자주 돌리거나 동시 사용자가 늘면 이쪽 |

디스크는 DB 약 180MB + 이미지 약 2.5GB + 백업으로 60GB 면 충분하다.

> 요금은 자주 바뀐다. 결제 전에 Lightsail 요금 페이지에서 현재가를 확인할 것.
> 리전은 **서울(ap-northeast-2)** 로 한다. DB에 대표자 성명·연락처가 들어 있어
> 국내 리전에 두면 개인정보 국외이전 고지 의무가 생기지 않는다.

## 2. 인스턴스 만들기

Lightsail 콘솔 → 인스턴스 생성

- 리전: **서울**
- 플랫폼: Linux/Unix
- 블루프린트: **OS 전용 → Ubuntu 24.04 LTS** (앱 포함 이미지 말고)
- 플랜: 위 표 참고
- 키 페어: 새로 만들고 `.pem` 을 안전한 곳에 보관

생성 후 **고정 IP(Static IP)를 연결**한다. 연결하지 않으면 재시작 때 주소가 바뀐다.

### 방화벽

인스턴스 → 네트워킹 → IPv4 방화벽. **80, 443, 22 만** 연다.

| 포트 | 용도 | 제한 |
|---|---|---|
| 22 | SSH | 가능하면 사무실 공인 IP 만 허용 |
| 80 | HTTP (인증서 발급·HTTPS 리다이렉트) | 전체 |
| 443 | HTTPS | 전체 |

**5432(DB)와 8000(API)은 절대 열지 않는다.** compose 가 내부 네트워크로만 연결한다.

## 3. 설치

SSH 접속 후:

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo tee /etc/apt/keyrings/docker.asc > /dev/null
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER && newgrp docker
```

2GB 인스턴스라면 적재 중 메모리 여유를 위해 스왑을 둔다:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 4. 도메인과 HTTPS

인터넷에 열면서 HTTP 로 두면 **로그인 비밀번호가 평문으로 흐른다.** 도메인을 붙이고
HTTPS 를 쓴다. Caddy 가 Let's Encrypt 인증서를 자동 발급·갱신한다.

사내 도메인에 A 레코드를 추가한다.

```
npo.example.co.kr.   A   <Lightsail 고정 IP>
```

도메인을 당장 못 쓰면 `SITE_ADDRESS=:80` 으로 HTTP 임시 운영은 가능하지만, 그 상태로
실제 영업에 쓰지는 말 것.

## 5. 배포

```bash
git clone https://github.com/dwww9292-collab/nonprofit.git
cd nonprofit
cp .env.example .env
```

`.env` 를 채운다. **비밀값은 로컬에서 쓰던 것을 재사용하지 말고 새로 만든다.**

```bash
python3 -c "import secrets; print('JWT_SECRET=' + secrets.token_urlsafe(48))"
python3 -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(24))"
python3 -c "import secrets; print('ADMIN_PASSWORD=' + secrets.token_urlsafe(16))"
```

외부 공개용으로 아래를 넣는다.

```dotenv
BIND_ADDR=127.0.0.1                  # Caddy 가 앞에 있으므로 호스트에 직접 열지 않는다
SITE_ADDRESS=npo.example.co.kr       # 도메인. 없으면 :80
ACME_EMAIL=admin@example.co.kr       # 인증서 만료 알림
```

기동:

```bash
docker compose -f docker-compose.yml -f docker-compose.aws.yml up -d --build
docker compose ps
docker compose logs -f caddy          # 인증서 발급 확인 (certificate obtained)
```

`https://npo.example.co.kr` 로 접속된다.

## 6. 데이터 옮기기

로컬에서 백업을 떠서 올린다.

```bash
# 로컬 (Windows PowerShell)
./ops/backup.sh
scp -i key.pem backups/npo-*.sql.gz ubuntu@<고정IP>:~/nonprofit/backups/

# 서버
cd ~/nonprofit && ./ops/restore.sh backups/npo-<날짜>.sql.gz
```

원본 엑셀을 다시 적재해도 되지만(`scripts.ingest auto`), 그러면 영업 담당 배정·활동
기록 같은 운영 데이터가 따라오지 않는다. 백업/복원 쪽이 맞다.

## 7. 인터넷에 열면서 반드시 할 것

- [ ] `.env` 비밀값 3개를 **새로 생성**했다 (로컬 값 재사용 금지)
- [ ] 초기 관리자 비밀번호를 로그인 후 바꿨다
- [ ] 사용자를 **사람별로** 만들었다 (설정 → 사용자 관리). 관리자 계정 공유 금지
- [ ] 방화벽에 80/443/22 만 열려 있다. 5432·8000 은 닫혀 있다
- [ ] HTTPS 로 접속된다 (`https://` 에서 자물쇠)
- [ ] 자동 백업이 돌고 있다 — `ops/backup.sh` 를 cron 에 건다

```bash
mkdir -p ~/nonprofit/backups
( crontab -l 2>/dev/null; echo "10 3 * * * cd $HOME/nonprofit && ./ops/backup.sh >> backups/backup.log 2>&1" ) | crontab -
```

- [ ] 백업을 인스턴스 밖으로도 보낸다 (Lightsail 스냅샷 자동화 또는 S3)
      — 인스턴스가 죽으면 그 안의 백업도 같이 죽는다
- [ ] Lightsail → 인스턴스 → 스냅샷 → **자동 스냅샷 활성화**

## 8. 비용 감각

| 항목 | 대략 |
|---|---|
| Lightsail 2GB | 월 $12 안팎 |
| Lightsail 4GB | 월 $24 안팎 |
| 고정 IP | 인스턴스에 연결돼 있으면 무료 |
| 자동 스냅샷 | 사용량 과금, 보통 월 $1~3 |
| 도메인 | 보유 중이면 0 |

사내망 전용으로 충분하다면 `docs/08-deploy.md`(사내 서버)는 추가 비용이 0 이다.
외부 접속만 가끔 필요하다면 Tailscale(무료 등급)로 사내 서버에 붙는 방법도 있다
— `docs/08-deploy.md` 4절.
