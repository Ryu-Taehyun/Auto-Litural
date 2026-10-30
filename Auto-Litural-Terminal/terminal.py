"""Launch the standalone, menu-driven terminal edition."""
import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description='AUTO-LITURAL Terminal Edition')
    parser.add_argument('--no-color', action='store_true', help='Disable terminal colors')
    parser.add_argument('--check', action='store_true', help='Check modules and assets without opening Chrome')
    args = parser.parse_args()
    try:
        from colorama import just_fix_windows_console
        from terminal_app.menu import Console, Menu
        import pyfiglet
    except ModuleNotFoundError:
        print('Missing packages. Run start.cmd, or: python -m pip install -r requirements.txt')
        return 1
    just_fix_windows_console()
    color = not args.no_color and not os.environ.get('NO_COLOR') and sys.stdout.isatty()
    console = Console(color=color)
    if args.check:
        from terminal_app.runner import prepare, browser_module
        try:
            for ritual in ('morning','finish'): prepare(ritual)
            browser_module().chrome_path()
        except Exception as error:
            console.write(f'[ERROR] {error}', 'warn')
            return 1
        console.banner()
        console.write('[OK] 모듈·CSV·Chrome 설치 경로 확인 완료. 브라우저는 열지 않았습니다.', 'good')
        return 0
    try:
        Menu(console).loop()
    except (EOFError, KeyboardInterrupt):
        console.write('\n종료합니다. Chrome은 유지됩니다.', 'blue')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
