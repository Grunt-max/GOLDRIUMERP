# Goldrium ERP 작업 및 배포 흐름

## 고정 브랜치

- 집 데스크톱: `a`
- 사무실 노트북: `b`
- NCP 운영 서버: `main`

Windows의 대소문자 브랜치 혼선을 피하기 위해 실제 브랜치 이름은 항상 소문자를 사용합니다.

## 기본 원칙

1. 한 시점에는 한 PC에서만 코드를 수정합니다.
2. 작업을 시작하기 전에 해당 PC의 브랜치를 최신 `main`과 동기화합니다.
3. 작업을 끝낼 때 Django 검사와 전체 테스트를 통과시킵니다.
4. 작업 브랜치를 먼저 GitHub에 올린 뒤 `main`을 빠른 전진 방식으로 갱신합니다.
5. 반대편 작업 브랜치도 같은 커밋으로 빠른 전진시킵니다.
6. NCP는 `main`만 배포합니다.
7. `db.sqlite3`, `media`, `.env`, `config/marketplace-secrets.ps1`은 Git으로 전송하지 않습니다.
8. 운영 DB는 배포 스크립트가 SQLite 온라인 백업을 만든 뒤 마이그레이션합니다.

## 작업 시작

사무실에서는:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sync-workstation.ps1 -Branch b
```

집에서는:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sync-workstation.ps1 -Branch a
```

작업 폴더에 미커밋 변경이 있거나 `main`과 빠른 전진으로 합칠 수 없으면 스크립트가 중단됩니다. 이 경우 임의로 reset하거나 force push하지 않습니다.

## 작업 종료와 운영 반영

모든 명령을 Codex를 통해 다음 순서로 수행합니다.

1. `manage.py check`
2. `manage.py test`
3. 현재 작업 브랜치에 커밋
4. 현재 작업 브랜치를 GitHub에 push
5. `main`과 반대편 브랜치를 같은 커밋으로 빠른 전진
6. NCP에서 `scripts/deploy-ncp.sh` 실행
7. 운영 서비스와 HTTPS 로그인 페이지 확인

## 충돌 방지

- 낮에 사무실 작업을 끝내고 배포까지 완료한 뒤 집 작업을 시작합니다.
- 저녁 집 작업을 끝내고 배포까지 완료한 뒤 다음 날 사무실 작업을 시작합니다.
- 양쪽에서 동시에 수정했거나 빠른 전진이 불가능하면 자동 push를 중단하고 변경 내용을 비교해 병합합니다.
- `git push --force`, `git reset --hard`, `git clean -fdx`는 운영 흐름에서 사용하지 않습니다.

## 운영 데이터

- 운영 DB: `/srv/goldrium/app/db.sqlite3`
- 운영 미디어: `/srv/goldrium/app/media`
- 운영 백업: `/srv/goldrium/backups`
- 운영 서비스: `goldrium-erp.service`
- 운영 배포 브랜치: `main`

