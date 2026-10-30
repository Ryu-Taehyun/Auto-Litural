# AUTO-LITURAL Terminal Edition

기존 Auto-Litural에서 분리한 Windows용 터미널 버전입니다. 웹 서버 없이 메뉴에서 아침/마무리 리추얼을 선택하고 Chrome 입력을 실행합니다. 기존 웹 버전과 분리된 `Auto-Litural-Terminal` 폴더로 제공합니다. 배너는 pyfiglet의 shadow 글꼴과 보라색을 사용합니다.

## 실행

1. ZIP을 **완전히 압축 해제**합니다.
2. Windows에 Python 3.11 이상과 Google Chrome을 설치합니다. Python 설치 시 `Add Python to PATH`를 선택하세요.
3. 폴더 안의 **start.cmd**를 더블 클릭합니다. 처음에는 인터넷으로 필요한 패키지를 설치하므로 잠시 기다립니다.

실행기는 이 폴더의 `.venv`에 패키지를 설치합니다. 기존 프로젝트의 환경을 사용하거나 변경하지 않습니다. 브라우저는 설치된 Google Chrome을 사용하므로 별도의 `playwright install`은 필요 없습니다.

PowerShell에서 직접 실행할 수도 있습니다.

```powershell
cd "압축을 푼 Auto-Litural-Terminal 폴더 경로"
.\start.cmd
```

## 메뉴

```text
1 : Start Write
2 : Morning / Finish
3 : Writing Speed / Type
4 : Partner Name
5 : Exit
```

- **2번**: Morning(아침) 또는 Finish(마무리)를 선택합니다.
- **3번**: Humanize는 입력·클릭·체크마다 6~12초를 무작위로 기다립니다. Instant는 추가 대기 없이 입력합니다. Custom은 각 동작 전 대기 시간을 0~3000ms로 지정합니다. Instant에도 페이지 로딩과 요소 준비를 기다리는 시간은 필요합니다.
- **4번**: 동료 이름 1~3명을 쉼표나 띄어쓰기로 구분해서 입력합니다. 예: `홍길동, 김하늘`. 이름은 각각 30자 이내이며 이름 자체에 공백은 사용할 수 없습니다.
- **1번**: 2~4번 설정을 검사합니다. 미설정 또는 잘못된 값이 있으면 경고하고 해당 값을 다시 입력받습니다. 설정이 유효하면 주의사항과 실행할 설정을 보여 줍니다. **START**를 입력해야 실제 실행됩니다. 다른 입력은 취소입니다.
- **5번**: 터미널 프로그램을 종료합니다. Chrome은 직접 닫습니다.

설정 변경 후에는 터미널 화면을 지우고 배너와 현재 설정을 다시 표시합니다. 실행 완료·오류·취소 결과는 Enter를 누를 때까지 표시하며, Enter를 누르면 화면을 지우고 메뉴로 돌아갑니다. 입력 프롬프트는 `>>`입니다.

설정은 실행 중에만 유지되고 프로그램을 다시 열면 새로 입력해야 합니다. 하위 메뉴의 `0`은 돌아가기이며 Custom 시간 입력 중에는 `B`로 취소합니다.

## 로그인·실행·중지

처음 실행하면 터미널 전용 Chrome이 열립니다. Google 로그인과 추가 인증은 그 창에서 직접 완료하세요. 최대 5분 동안 기다립니다. 이후 실행에서는 이 전용 창의 로그인된 탭을 우선 재사용합니다. 튜토리얼 등 최초 안내가 있으면 직접 완료하고 다시 실행하세요.

진행 단계와 대기 시간은 터미널에 표시됩니다. 실행 중 **Ctrl+C**를 누르면 입력을 중지하고 메뉴로 돌아갑니다. 이미 입력된 내용은 되돌리지 않으며 Chrome 창은 유지합니다. 메뉴에서 Ctrl+C를 누르면 프로그램이 종료됩니다.

**최종 저장 버튼은 자동으로 누르지 않습니다.** 완료 후 Chrome에서 내용과 대상 날짜를 확인하고 직접 저장하세요. 기존 기록이 있으면 수정 화면에 들어가 입력 내용을 바꿀 수 있으므로 실행 전 확인하세요.

실행 전 다음 문구를 포함한 경고가 매번 표시됩니다.

> 이 프로그램 사용으로 평가 점수 하락 등 불이익이 발생하더라도 개발자는 책임을 지지 않습니다.

이 버전은 화면이 보이는 Chrome을 사용합니다. 전용 프로필은 `%LOCALAPPDATA%\AutoLituralTerminalChrome`, 연결 포트는 `127.0.0.1:9224`입니다. 일반 Chrome 및 기존 웹 버전의 프로필과 분리됩니다. 로그인 정보가 들어 있는 전용 프로필을 다른 사람에게 공유하지 마세요.

## 파일 구조

```text
Auto-Litural-Terminal/
  start.cmd                 Windows 실행기
  terminal.py               터미널 시작점
  requirements.txt          필요한 패키지
  terminal_app/
    menu.py                 배너·메뉴·경고·확인
    settings.py             설정 검사
    runner.py               자동화 연결·속도·진행 로그
  Playwright/
    main.py                 아침 리추얼 입력
    close.py                마무리 리추얼 입력
    chrome.py               Chrome 연결·수동 로그인
  csv/                      입력 문장 자료
  tests/                    로컬 동작 검사
```

실행 시작점은 `terminal.py`입니다. `Playwright`의 세 파일을 따로 실행하지 마세요. 기존 입력 함수를 복사해 사용하고 CSV 경로를 이 새 폴더 기준으로 조정했습니다. 원본 프로젝트 파일은 수정하지 않았습니다. CSV 문장은 한 열 형식을 유지해서 편집하세요.

## 문제 확인

브라우저를 열지 않고 모듈, CSV, Chrome 설치 위치를 확인하려면:

```powershell
.\start.cmd --check
```

Chrome 경로를 찾지 못하는 경우 설치 경로를 지정할 수 있습니다.

```powershell
$env:AUTO_LITURAL_CHROME = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
.\start.cmd
```

로그인이나 학습 메뉴에서 멈추면 Chrome 창에서 로그인 상태, 튜토리얼 완료 여부, 학생 권한을 확인한 다음 다시 실행하세요. 사이트 화면 구조가 달라지면 입력 선택자 수정이 필요할 수 있습니다. 연결 오류가 나면 터미널 전용 Chrome 창을 닫고 다시 실행해 보세요.

색상 표시가 어색하면 Windows Terminal을 사용하거나 `start.cmd --no-color`로 실행합니다. 실행기는 한글 경로/문구를 위해 UTF-8을 설정하며 배치 파일 자체는 영문으로 작성했습니다.

## 개발 확인

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

설정 재입력, 실행 동의, 색상 배너, 속도와 중지, 기존 탭 선택, 두 종류 리추얼 입력을 검사하는 15개 테스트를 포함합니다. 자동화 입력 검사는 가짜 페이지를 사용하며 실제 계정 로그인·실제 사이트 저장을 테스트하지 않습니다.
