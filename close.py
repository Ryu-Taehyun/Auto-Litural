# 마무리 리추얼 자동화
# 주의사항 : 크롬 디버깅 모드로 실행 필요 (동료 이름 입력 후 자동으로 켜짐)
import asyncio
import random
import pandas as pd
from playwright.async_api import async_playwright, expect
from chrome import ensure_chrome

url = "https://aleph-omega.vercel.app/login"

MIN_PEERS = 1
MAX_PEERS = 3


# csv 에서 랜덤 문장 n개 뽑기 (중복 없이, 문장이 모자라면 중복 허용)
def pick(path, n=1):
    sentences = pd.read_csv(path, encoding="utf-8-sig", header=None).iloc[:, 0].dropna().astype(str).tolist()
    if len(sentences) >= n:
        return random.sample(sentences, n)
    return [random.choice(sentences) for _ in range(n)]


# 동료 이름 입력 받기
def ask_peers():
    while True:
        raw = input(f"동료 이름을 입력하세요 ({MIN_PEERS}~{MAX_PEERS}명, 띄어쓰기나 쉼표로 구분): ")
        names = raw.replace(",", " ").split()
        if MIN_PEERS <= len(names) <= MAX_PEERS:
            return names
        print(f"[WARN] 동료는 {MIN_PEERS}~{MAX_PEERS}명이어야 합니다. (입력: {len(names)}명)")


# 입력 행 개수를 n개로 맞추기
async def set_row_count(page, rows, add_btn, remove_btn, n):
    while await rows.count() < n:
        count = await rows.count()
        await add_btn.click()
        await expect(rows).to_have_count(count + 1, timeout=10000)

    while await rows.count() > n:
        count = await rows.count()
        await remove_btn.click()
        await expect(rows).to_have_count(count - 1, timeout=10000)


# 페이지 오픈 / 로그인 대기
async def open_page(url, peers):
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        page = await browser.new_page()
        await page.goto(url)

        await page.locator("button#googleBtn").click()
        print("[INFO] LOGIN WAIT")
        await page.wait_for_url("**/tutorial**", timeout=0)

        print("[INFO] LOGIN SUCCESS")
        await find_button(page, peers)

        await asyncio.Event().wait()


# 버튼 찾기 (마무리 리추얼로 이동)
async def find_button(page, peers):
    await page.locator("summary", has_text="학습 메뉴").click()
    await page.locator('a[data-nav-key="ritual-close"]').click()

    # 이미 기록이 있으면 수정 모드로 진입
    edit_btn = page.get_by_role("button", name="기록 수정하기")
    try:
        await edit_btn.wait_for(state="visible", timeout=3000)
        await edit_btn.click()
    except Exception:
        pass

    await write_1(page, peers)


# 강점 행동 돌아보기
async def write_1(page, peers):
    await page.locator("#stepTitle").filter(
        has_text="아침에 정한 강점 행동을 돌아봅니다").wait_for(state="visible", timeout=30000)
    print("[INFO] Write_1")
    await page.locator("#closeStatus-done").check()
    await page.locator("#strengthEffort").fill(pick(r"csv\close_effort.csv")[0])
    await page.locator("#selfNote").fill(pick(r"csv\close_note.csv")[0])
    await page.locator("#nextBtn").click()
    await write_2(page, peers)


# 감사 나누기 (동료)
async def write_2(page, peers):
    await page.locator("#stepTitle").filter(
        has_text="오늘 감사했던 일을 동료들과 나눕니다").wait_for(state="visible", timeout=30000)
    print("[INFO] Write_2")
    print("입력 대상:", peers)
    await page.locator("#myShare").fill(pick(r"csv\close_share.csv")[0])

    rows = page.locator('[id^="close-peer-story-"]')
    await set_row_count(
        page, rows,
        page.locator("#closePeerAddRow"),
        page.locator(".recognition-given-row .recognition-row-remove").last,
        len(peers),
    )

    stories = pick(r"csv\close_peer_story.csv", len(peers))
    for i, person in enumerate(peers):
        await page.locator(f"#close-peer-{i}").fill(person)
        await page.locator(f"#close-peer-story-{i}").fill(stories[i])

    await page.locator("#nextBtn").click()
    await write_final(page, peers)


# 감사일기 (동료 수만큼 작성)
async def write_final(page, peers):
    await page.locator("#stepTitle").filter(
        has_text="오늘의 감사일기").wait_for(state="visible", timeout=30000)
    print("[INFO] Write_FINAL")

    rows = page.locator('[id^="gratitude-event-"]')
    await set_row_count(
        page, rows,
        page.locator("#gratitudeAddRow"),
        page.locator("#gratitudeRemoveRow"),
        len(peers),
    )

    events = pick(r"csv\close_gratitude.csv", len(peers))
    for i, person in enumerate(peers):
        await page.locator(f"#gratitude-event-{i}").fill(events[i])
        await page.locator(f"#gratitude-person-{i}").fill(person)
    # await page.get_by_role("button", name="저장하고 마무리").click()


peers = ask_peers()
ensure_chrome()
asyncio.run(open_page(url, peers))
