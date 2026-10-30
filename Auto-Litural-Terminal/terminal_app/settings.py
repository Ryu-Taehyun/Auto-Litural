from dataclasses import dataclass, field


@dataclass
class Settings:
    ritual: str | None = None
    speed: str | None = None
    delay_ms: int = 0
    partners: list[str] = field(default_factory=list)


def parse_partners(raw):
    if not isinstance(raw, str) or len(raw) > 120:
        raise ValueError('이름 입력은 120자 이내여야 합니다.')
    if any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise ValueError('이름에 제어 문자를 넣을 수 없습니다.')
    names = raw.replace(',', ' ').split()
    if not 1 <= len(names) <= 3:
        raise ValueError('동료 이름은 1~3명을 입력하세요. 쉼표 또는 띄어쓰기로 구분합니다.')
    if any(len(name) > 30 for name in names):
        raise ValueError('이름은 각각 30자 이내로 입력하세요.')
    return names


def validate(settings):
    errors = {}
    if settings.ritual not in ('morning', 'finish'):
        errors[2] = 'Morning / Finish를 다시 설정하세요.'
    if settings.speed not in ('humanize', 'instant', 'custom'):
        errors[3] = 'Writing Speed / Type을 다시 설정하세요.'
    elif settings.speed == 'custom' and (type(settings.delay_ms) is not int or not 0 <= settings.delay_ms <= 3000):
        errors[3] = '직접 딜레이는 0~3000ms의 정수여야 합니다.'
    try:
        if not isinstance(settings.partners, list) or not all(isinstance(name,str) and name and not any(c.isspace() or c==',' for c in name) for name in settings.partners):
            raise ValueError('동료 이름을 다시 입력하세요.')
        parse_partners(','.join(settings.partners))
    except ValueError as error:
        errors[4] = str(error)
    return errors


def speed_label(settings):
    if not isinstance(settings.speed,str): return ''
    return {'humanize':'Humanize · 6~12초 무작위 대기', 'instant':'Instant · 추가 대기 없음',
            'custom':f'Custom · {settings.delay_ms}ms'}.get(settings.speed, '')
