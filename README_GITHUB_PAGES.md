# ROLLU GitHub Pages 정리본

## 현재 배포용 구성
- `index.html`: 기존 ROLLU 오프라인 미리보기 화면을 홈페이지로 사용합니다. 가상 데이터 기반이며 로그인/실제 Riot API/서버 저장은 동작하지 않습니다.
- `backend/`: 기존 FastAPI/Python/SQLite 소스와 테스트를 보존했습니다. GitHub Pages는 Python 서버를 실행하지 않으므로 현재 배포에서는 사용하지 않습니다. 추후 Cloud Run 이전 작업에 사용합니다.

## GitHub Pages 배포
1. 저장소 루트에 이 압축파일의 **내용물**을 업로드합니다 (`index.html`이 저장소 최상위에 있어야 합니다).
2. GitHub 저장소 Settings → Pages로 이동합니다.
3. Build and deployment에서 Deploy from a branch를 선택합니다.
4. Branch `main`, folder `/(root)`를 선택하고 Save 합니다.
5. 몇 분 후 표시되는 Pages URL로 접속합니다.

## 다음 단계
Firebase Authentication 이메일/비밀번호 로그인과 Firestore 저장을 추가하고, 운영진 승인 및 서버 측 권한 검증을 구현합니다. Riot API 키는 절대 브라우저 코드나 GitHub에 넣지 않습니다. Python 백엔드는 추후 Cloud Run 등 서버 환경에 배포해야 합니다.
