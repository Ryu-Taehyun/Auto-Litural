# 주의사항 : 크롬 디버깅 모드로 실행 필요
# "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\ChromeDebug"
import requests
import asyncio
import random
import pandas as pd
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, expect

url = "https://aleph-omega.vercel.app/login"

# 페이지 오픈 / 로그인 대기
async def open_page(url):
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        page = await browser.new_page()
        await page.goto(url)

        await page.locator("button#googleBtn").click()
        print("[INFO] LOGIN WAIT")
        await page.wait_for_url("**/tutorial**", timeout=0)

        print("[INFO] LOGIN SUCCESS")
        await find_button(page)

        await asyncio.Event().wait()

# 버튼 찾기 (리추얼로 이동)
async def find_button(page):
    await page.locator("summary", has_text="학습 메뉴").click()
    await page.locator('a[data-nav-key="ritual-open"]').click()
    await page.get_by_role("button", name="기록 수정하기").click()
    await radio_check(page)

# 체크박스
async def radio_check(page):
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

    print("[INFO] CheckBox")
    await page.get_by_role("button", name="기록하고 다음").click()
    await write_1(page)

# 편안했던 장면 작성
async def write_1(page):
    await page.locator("#stepTitle").filter(
    has_text="편안했던 장면 하나 떠올리기").wait_for(state="visible",timeout=30000)
    name = pd.read_csv(r"csv\Title.csv", encoding="utf-8", header=None)
    print("[INFO] Write_1")
    await page.locator("#memory").fill(str(name.iloc[random.randrange(len(name)), 0]))
    await page.get_by_role("button", name="기록하고 다음").click()
    await write_2(page)

# 장점 작성
async def write_2(page):
    await page.locator("#stepTitle").filter(
    has_text="내 인생의 기억에서 강점(장점)과 가치 찾기").wait_for(state="visible",timeout=30000)
    csv1 = pd.read_csv(r"csv\1.csv", encoding="utf-8", header=None)
    csv2 = pd.read_csv(r"csv\2.csv", encoding="utf-8", header=None)
    csv3 = pd.read_csv(r"csv\3.csv", encoding="utf-8", header=None)
    print("[INFO] Write_2")
    await page.locator("#strengthEvidenceScene").fill(str(csv1.iloc[random.randrange(len(csv1)), 0]))
    await page.locator("#strengthEvidenceOutcome").fill(str(csv2.iloc[random.randrange(len(csv2)), 0]))
    await page.locator("#strengths").fill(str(csv3.iloc[random.randrange(len(csv3)), 0]))
    await page.get_by_role("button", name="기록하고 다음").click()
    await write_3(page)

async def write_3(page):
    await page.locator("#stepTitle").filter(
        has_text="남에 대한 평가는 나에 대한 평가"
    ).wait_for(state="visible", timeout=30000)

    name = pd.read_csv(r"csv\Name.csv", encoding="utf-8-sig", header=None)
    csv4 = pd.read_csv(r"csv\4.csv", encoding="utf-8", header=None)

    # 이름 3개 고정
    names = name.iloc[:, 0].dropna().astype(str).tolist()[:3]

    if len(names) < 3:
        print("이름이 3개 미만입니다.")
        return

    print("[INFO] Write_3")
    print("입력 대상:", names)

    rows = page.locator('[id^="recognition-peer-"]')

    # 입력 행을 3개로 맞추기
    while await rows.count() < 3:
        count = await rows.count()
        await page.locator("#recognitionAddRow").click()
        await expect(rows).to_have_count(count + 1, timeout=10000)

    while await rows.count() > 3:
        count = await rows.count()
        await page.locator(".recognition-row-remove").last.click()
        await expect(rows).to_have_count(count - 1, timeout=10000)

    # 3명 모두 입력
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
    csv5 = pd.read_csv(r"csv\5.csv", encoding="utf-8-sig", header=None)
    sentences = csv5.iloc[:, 0].dropna().astype(str).tolist()
    if sentences and sentences[0] == "문장":
        sentences.pop(0)
    selected = random.sample(sentences, 3)

    for i, sentence in enumerate(selected):
        await page.locator(f"#recognition-received-{i}").fill(sentence)
    await page.get_by_role("button", name="기록하고 다음").click()
    print("[INFO] Write_4")
    await write_final(page)

# 마지막 긍정 목표
async def write_final(page):
    await page.locator("#stepTitle").filter(
        has_text="내가 주인이 되는 긍정의 목표").wait_for(state="visible", timeout=30000)
    csv6 = pd.read_csv(r"csv\6.csv", encoding="utf-8", header=None)
    csv7 = pd.read_csv(r"csv\7.csv", encoding="utf-8", header=None)
    print("[INFO] Write_FINAL")
    await page.locator("#planStrengthValue").fill(str(csv6.iloc[random.randrange(len(csv6)), 0]))
    await page.locator("#planFirstAction").fill(str(csv7.iloc[random.randrange(len(csv7)), 0]))
    # await page.get_by_role("button", name="계획 저장하고 아침 마치기").click()

asyncio.run(open_page(url))
