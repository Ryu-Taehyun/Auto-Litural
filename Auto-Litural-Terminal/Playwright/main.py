"""Ritual field filling used by the terminal launcher. Never clicks final save."""
from pathlib import Path
import random
import pandas as pd
from playwright.async_api import expect

DATA = Path(__file__).resolve().parent.parent / 'csv'


async def find_button(page, names):
    await page.locator("summary", has_text="학습 메뉴").click()
    await page.locator('a[data-nav-key="ritual-open"]').click()

    # 이미 기록이 있으면 수정 모드로 진입 (오늘 첫 기록이면 버튼이 없음)
    # 버튼이나 첫 단계 입력창 중 먼저 뜨는 쪽을 기다린 뒤 판단 (로딩이 느려도 버튼을 놓치지 않게)
    edit_btn = page.get_by_role("button", name="기록 수정하기")
    first_radio = page.locator('input[name="breathAnchor"][value="breath"]')
    await edit_btn.or_(first_radio).first.wait_for(state="visible", timeout=30000)
    if await edit_btn.is_visible():
        await edit_btn.click()

    await radio_check(page, names)


async def radio_check(page, names):
    radio = page.locator(
        'input[name="breathAnchor"][value="breath"]'
    )
    await radio.check()
    radio1 = page.locator(
        'input[name="breathEyes"][value="open"]'
    )
    await radio1.check()
    radio2 = page.locator(
        'input[name="breathPosture"][value="seated"]'
    )
    await radio2.check()

    # 호흡 안내: "5분 시작" → "여기까지"를 눌러야 다음 단계로 넘어갈 수 있음
    # 수정 모드에서는 시작 버튼이 없을 수 있어 보일 때만 누름
    start_btn = page.locator("#breathStartBtn")
    try:
        await start_btn.wait_for(state="visible", timeout=3000)
        await start_btn.click()
        await page.locator("#breathStopBtn").click()
    except Exception:
        print("[INFO] 호흡 시작 버튼 없음 - 건너뜀")

    print("[INFO] CheckBox")
    await page.get_by_role("button", name="기록하고 다음").click()
    await write_1(page, names)


async def write_1(page, names):
    await page.locator("#stepTitle").filter(
    has_text="편안했던 장면 하나 떠올리기").wait_for(state="visible",timeout=30000)
    name = pd.read_csv(DATA / 'Title.csv', encoding="utf-8", header=None)
    print("[INFO] Write_1")
    await page.locator("#memoryMode-scene").check()
    await page.locator("#memory").fill(str(name.iloc[random.randrange(len(name)), 0]))
    await page.get_by_role("button", name="기록하고 다음").click()
    await write_2(page, names)


async def write_2(page, names):
    await page.locator("#stepTitle").filter(
    has_text="내 인생의 기억에서 강점(장점)과 가치 찾기").wait_for(state="visible",timeout=30000)
    csv1 = pd.read_csv(DATA / '1.csv', encoding="utf-8", header=None)
    csv2 = pd.read_csv(DATA / '2.csv', encoding="utf-8", header=None)
    csv3 = pd.read_csv(DATA / '3.csv', encoding="utf-8", header=None)
    print("[INFO] Write_2")
    await page.locator("#strengthEvidenceScene").fill(str(csv1.iloc[random.randrange(len(csv1)), 0]))
    await page.locator("#strengthEvidenceOutcome").fill(str(csv2.iloc[random.randrange(len(csv2)), 0]))
    await page.locator("#strengths").fill(str(csv3.iloc[random.randrange(len(csv3)), 0]))
    await page.get_by_role("button", name="기록하고 다음").click()
    await write_3(page, names)


async def write_3(page, names):
    await page.locator("#stepTitle").filter(
        has_text="남에 대한 평가는 나에 대한 평가"
    ).wait_for(state="visible", timeout=30000)

    csv4 = pd.read_csv(DATA / '4.csv', encoding="utf-8", header=None)

    print("[INFO] Write_3")
    print("입력 대상:", names)

    rows = page.locator('[id^="recognition-peer-"]')

    # 입력 행을 이름 수에 맞추기
    n = len(names)
    while await rows.count() < n:
        count = await rows.count()
        await page.locator("#recognitionAddRow").click()
        await expect(rows).to_have_count(count + 1, timeout=10000)

    while await rows.count() > n:
        count = await rows.count()
        await page.locator(".recognition-row-remove").last.click()
        await expect(rows).to_have_count(count - 1, timeout=10000)

    # 입력한 이름 모두 입력
    for i, person in enumerate(names):
        await page.locator(f"#recognition-peer-{i}").fill(person)
        await page.locator(f"#recognition-positive-{i}").fill(
            str(csv4.iloc[random.randrange(len(csv4)), 0])
        )

    await write_4(page)


async def write_4(page):
    await page.locator("#recognition-received-0").wait_for(
        state="visible", timeout=30000
    )
    csv5 = pd.read_csv(DATA / '5.csv', encoding="utf-8-sig", header=None)
    sentences = csv5.iloc[:, 0].dropna().astype(str).tolist()
    if sentences and sentences[0] == "문장":
        sentences.pop(0)
    # 받은 인정 칸 수는 사이트 기준으로 따라감 (이름 수와 같은지 확인 못 함)
    count = await page.locator('[id^="recognition-received-"]').count()
    selected = random.sample(sentences, count)

    for i, sentence in enumerate(selected):
        await page.locator(f"#recognition-received-{i}").fill(sentence)
    await page.get_by_role("button", name="기록하고 다음").click()
    print("[INFO] Write_4")
    await write_final(page)


async def write_final(page):
    await page.locator("#stepTitle").filter(
        has_text="내가 주인이 되는 긍정의 목표").wait_for(state="visible", timeout=30000)
    csv6 = pd.read_csv(DATA / '6.csv', encoding="utf-8", header=None)
    csv7 = pd.read_csv(DATA / '7.csv', encoding="utf-8", header=None)
    print("[INFO] Write_FINAL")
    await page.locator("#planStrengthValue").fill(str(csv6.iloc[random.randrange(len(csv6)), 0]))
    await page.locator("#planFirstAction").fill(str(csv7.iloc[random.randrange(len(csv7)), 0]))
