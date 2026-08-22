# 골드리움 킹 운영 구성

- ERP 본체는 `127.0.0.1:8000`에서만 Waitress로 실행합니다.
- 외부 공유기에는 포트 포워딩을 설정하지 않습니다.
- 승인된 장치는 Tailscale Serve의 HTTPS 주소로만 접속합니다.
- `tailscale funnel`은 사용하지 않습니다.
- 운영 시작: `powershell -ExecutionPolicy Bypass -File scripts\start-production.ps1`
- 수동 백업: `powershell -ExecutionPolicy Bypass -File scripts\backup-erp.ps1`
- 자동 백업은 Windows 작업 스케줄러에서 매일 실행하도록 등록합니다.
- 복구에는 같은 시점의 `db.sqlite3`와 `media` 폴더를 함께 사용합니다.
