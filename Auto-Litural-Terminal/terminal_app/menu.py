from copy import deepcopy
import os
import sys
from .settings import Settings, parse_partners, validate, speed_label

DISCLAIMER = (
    '이 프로그램 사용으로 평가 점수 하락 등 불이익이 발생하더라도 개발자는 책임을 지지 않습니다.',
    '사용 여부와 입력 내용 확인에 대한 책임은 사용자에게 있습니다.',
    '기존 기록이 있으면 수정 화면에 들어가 내용을 채울 수 있습니다.',
    '입력 내용을 확인하고 최종 저장은 Chrome에서 직접 해 주세요.',
)


class Console:
    def __init__(self, input_fn=input, output_fn=print, color=False):
        self.input = input_fn
        self.output = output_fn
        self.color = color

    def styled(self, message, tone=''):
        colors = {'purple':'\033[95m','blue':'\033[94m','warn':'\033[93m','error':'\033[91m','good':'\033[92m'}
        prefix = colors.get(tone, '') if self.color else ''
        return prefix + str(message) + ('\033[0m' if prefix else '')

    def write(self, message='', tone=''):
        self.output(self.styled(message, tone))

    def ask(self, message):
        return self.input(message).strip()

    def clear(self):
        if self.output is print and sys.stdout.isatty():
            if os.name == 'nt':
                os.system('cls')
            else:
                self.output('\033[2J\033[3J\033[H', end='', flush=True)

    def banner(self):
        from pyfiglet import Figlet
        self.write(Figlet(font='shadow', width=200).renderText('AUTO-LITURAL').rstrip(), 'purple')


class Menu:
    def __init__(self, console=None, settings=None, run_fn=None):
        self.ui = console or Console(color=sys.stdout.isatty())
        self.settings = settings or Settings()
        if run_fn is None:
            from .runner import run_ritual
            run_fn = run_ritual
        self.run = run_fn

    def show(self):
        s = self.settings
        errors = validate(s)
        self.ui.write('\n' + '─' * 68, 'purple')
        status = self.ui.styled('UNSTABLE' if errors else 'STABLE', 'error' if errors else 'warn')
        self.ui.write(f'  1 : Start Write            [{status}]')
        ritual = 'Morning' if s.ritual == 'morning' else 'Finish' if s.ritual == 'finish' else ''
        rows = [(2, 'Morning / Finish', ritual), (3, 'Writing Speed / Type', speed_label(s)),
                (4, 'Partner Name', ', '.join(s.partners) if 4 not in errors else '')]
        for number, label, value in rows:
            suffix = f'[{value}]' if value and number not in errors else ''
            self.ui.write(f'  {number} : {label:<24}{suffix}'.rstrip())
        self.ui.write('  5 : Exit')
        self.ui.write('─' * 68, 'purple')

    def choose_ritual(self):
        while True:
            self.ui.write('\n[2] Morning / Finish\n  1 : Morning\n  2 : Finish\n  0 : Back')
            value = self.ui.ask('>> ')
            if value == '0': return False
            if value in ('1','2'):
                self.settings.ritual = 'morning' if value == '1' else 'finish'
                return True
            self.ui.write('[WARN] 1 또는 2를 다시 입력하세요.', 'warn')

    def choose_speed(self):
        while True:
            self.ui.write('\n[3] Writing Speed / Type\n  1 : Humanize  (입력·클릭마다 6~12초 무작위 대기)\n  2 : Instant   (추가 대기 없이 입력)\n  3 : Custom    (0~3000ms 직접 설정)\n  0 : Back')
            value = self.ui.ask('>> ')
            if value == '0': return False
            if value in ('1','2'):
                self.settings.speed = 'humanize' if value == '1' else 'instant'
                self.settings.delay_ms = 0
                return True
            if value == '3':
                raw = self.ui.ask('딜레이 ms (0~3000, B=취소) >> ')
                if raw.upper() == 'B': return False
                try:
                    delay = int(raw)
                    if not 0 <= delay <= 3000: raise ValueError
                except ValueError:
                    self.ui.write('[WARN] 0~3000의 정수를 다시 입력하세요.', 'warn')
                    continue
                self.settings.speed, self.settings.delay_ms = 'custom', delay
                return True
            self.ui.write('[WARN] 1~3 중에서 다시 선택하세요.', 'warn')

    def choose_partners(self):
        while True:
            self.ui.write('\n[4] Partner Name · 1~3명 / 쉼표 또는 띄어쓰기 구분')
            raw = self.ui.ask('이름 (예: 홍길동, 김하늘 / 0=취소) >> ')
            if raw == '0': return False
            try:
                self.settings.partners = parse_partners(raw)
                return True
            except ValueError as error:
                self.ui.write('[WARN] ' + str(error), 'warn')

    def start(self):
        errors = validate(self.settings)
        if errors:
            self.ui.write('\n[WARN] 설정값에 오류가 있습니다. 해당 값을 다시 입력하세요.', 'warn')
            for number, message in errors.items():
                self.ui.write(f'  {number}번: {message}', 'warn')
            editors = {2:self.choose_ritual, 3:self.choose_speed, 4:self.choose_partners}
            for number in errors:
                if not editors[number]():
                    self.ui.write('[CANCEL] 설정 입력을 취소했습니다. 실행하지 않습니다.', 'warn')
                    return
        if validate(self.settings):
            self.ui.write('[WARN] 설정이 아직 올바르지 않습니다. 2~4번을 다시 설정하세요.', 'warn')
            return
        self.ui.write('\n' + '═' * 68, 'warn')
        self.ui.write('  실행 전 주의사항', 'warn')
        for line in DISCLAIMER: self.ui.write('  ' + line, 'warn')
        self.ui.write('═' * 68, 'warn')
        self.ui.write(f'리추얼: {self.settings.ritual.upper()} / {speed_label(self.settings)}')
        self.ui.write('동료: ' + ', '.join(self.settings.partners))
        if self.ui.ask('동의하고 실행하려면 START 입력 (그 외=취소) >> ').upper() != 'START':
            self.ui.write('[CANCEL] 실행을 취소했습니다.', 'warn')
            return
        try:
            self.run(deepcopy(self.settings), self.ui.write)
        except KeyboardInterrupt:
            self.ui.write('\n[STOP] 자동 입력을 중지했습니다. 이미 입력한 내용과 Chrome은 유지됩니다.', 'warn')
        except RuntimeError as error:
            self.ui.write('[ERROR] ' + str(error), 'warn')
        except Exception as error:
            self.ui.write(f'[ERROR] {type(error).__name__}: 실행하지 못했습니다. Chrome 화면과 CSV 파일을 확인하세요.', 'warn')

    def loop(self):
        while True:
            self.ui.clear()
            self.ui.banner()
            self.show()
            choice = self.ui.ask('>> ')
            if choice == '5':
                self.ui.write('Auto-Litural을 종료합니다. Chrome은 직접 닫아 주세요.', 'blue')
                return
            handler = {'1':self.start,'2':self.choose_ritual,'3':self.choose_speed,'4':self.choose_partners}.get(choice)
            if handler:
                handler()
                if choice == '1':
                    self.ui.ask('결과를 확인한 뒤 Enter를 누르면 메뉴로 돌아갑니다. >> ')
            else:
                self.ui.write('[WARN] 1~5 중에서 다시 선택하세요.', 'warn')
                self.ui.ask('Enter를 눌러 다시 선택하세요. >> ')
