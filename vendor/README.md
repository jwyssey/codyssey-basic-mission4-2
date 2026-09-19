# 교육기관 제공 과제 2 실행 파일

## Docker에서 준비하기

교육기관에서 받은 ZIP을 이 폴더의 `agent-app-leak.zip`으로 복사한다. 직접 압축을 풀 필요는 없다. Docker 실행 도구가 Linux 아키텍처에 맞는 x86 또는 ARM64 파일만 임시 추출하고, ELF 형식을 확인한 뒤 UID 1000으로 실행한다. ZIP은 읽기 전용으로 연결하며 이미지와 Git에는 포함하지 않는다. 다른 PC에서는 원본 ZIP을 별도로 준비한다. 전체 절차는 [튜토리얼](../TUTORIAL.md)을 따른다.

## 기존 WSL 실측의 원본 정보

사용자가 제공한 `../agent-app-leak.zip`에서 `agent-leak-app-x86`을 추출했다. 현재 환경은 Linux x86_64다. 바이너리는 수정·디컴파일하지 않았다.

- ZIP SHA256: `249c9c2841718cb29ef2ed680668f328f5ee253354090225347e130a2e456641`
- 실행 파일 SHA256: `7e0a19cfa80ece6b547a5008273661f0d4d71e526e96b51e0d0f341dd1bb3e40`
- 크기: 6,502,016 bytes
- 형식: ELF 64-bit x86-64, 패키징된 Python 앱

```bash
unzip -p ../agent-app-leak.zip agent-leak-app-x86 > vendor/agent-leak-app-x86
chmod u+x vendor/agent-leak-app-x86
sha256sum vendor/agent-leak-app-x86
```

일반 계정에서 직접 실행하며 `python3 바이너리` 형태로 실행하지 않는다. ARM64 환경에서는 ZIP의 `agent-leak-app-arm64`를 사용한다. 바이너리는 `.gitignore`와 제출 ZIP에서 제외했으므로 다른 PC에서는 교육기관 배포 파일을 별도로 준비한다. 테스트 키는 명세의 공개된 실습 문자열 `agent_api_key_test`다.
