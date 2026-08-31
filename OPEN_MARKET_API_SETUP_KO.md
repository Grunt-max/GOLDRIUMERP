# 골드리움 킹 오픈마켓 API 설정

현재 오픈마켓관리는 읽기 전용입니다. 상품 목록을 조회해 ERP DB에 복사하지만 오픈마켓의 상품, 가격, 옵션, 재고를 수정하지 않습니다.

## 네이버 스마트스토어

1. 네이버 커머스API 센터(https://apicenter.commerce.naver.com/)에 로그인합니다.
2. 내 스토어 판매자 계정으로 애플리케이션을 등록합니다.
3. 애플리케이션 ID와 애플리케이션 시크릿을 발급받습니다.
4. 사용 API에서 상품 조회 권한을 사용할 수 있는지 확인합니다.

## 쿠팡

1. 쿠팡 WING(https://wing.coupang.com/)에 판매자 계정으로 로그인합니다.
2. 판매자 정보의 추가판매정보 또는 OPEN API 관리 화면으로 이동합니다.
3. OPEN API 키를 발급하고 Access Key, Secret Key를 확인합니다.
4. WING 화면의 업체코드(Vendor ID, 보통 A로 시작)를 확인합니다.

## ERP에 안전하게 입력

프로젝트 폴더에서 PowerShell로 다음 파일을 실행합니다.

```powershell
.\scripts\configure-marketplace-apis.ps1
```

화면 질문에 따라 다섯 값을 입력합니다. Secret은 입력 중 화면에 표시되지 않습니다.

- 네이버 애플리케이션 ID
- 네이버 애플리케이션 시크릿
- 쿠팡 Access Key
- 쿠팡 Secret Key
- 쿠팡 Vendor ID

값은 `config/marketplace-secrets.ps1`에 저장되며 `.gitignore`로 보호되어 GitHub에 올라가지 않습니다. 이 파일을 메신저, 이메일 또는 Codex 대화에 첨부하지 마세요.

입력 후 ERP 서버를 재시작하고 왼쪽 메뉴의 `오픈마켓관리`로 들어가 `상품 가져오기`를 누릅니다.

## 주의

- API 키는 스마트스토어·쿠팡 비밀번호가 아니며 각 판매자 센터에서 별도로 발급합니다.
- 키가 노출되면 즉시 판매자 센터에서 폐기하고 새 키를 발급합니다.
- `config/marketplace-secrets.ps1`은 백업 저장소에도 복사하지 않는 것을 권장합니다.
- 최초 수집 전에는 네이버와 쿠팡에서 테스트용 또는 읽기 권한이 정상인지 확인합니다.
