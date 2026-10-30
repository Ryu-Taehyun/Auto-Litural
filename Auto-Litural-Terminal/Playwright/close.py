"""Ritual field filling used by the terminal launcher. Never clicks final save."""
from pathlib import Path
import random
import pandas as pd
from playwright.async_api import expect

DATA = Path(__file__).resolve().parent.parent / 'csv'


def pick(path, n=1):
    sentences = pd.read_csv(path, encoding="utf-8-sig", header=None).iloc[:, 0].dropna().astype(str).tolist()
    if len(sentences) >= n:
        return random.sample(sentences, n)
    return [random.choice(sentences) for _ in range(n)]


async def set_row_count(page, rows, add_btn, remove_btn, n):
    while await rows.count() < n:
        count = await rows.count()
        await add_btn.click()
        await expect(rows).to_have_count(count + 1, timeout=10000)

    while await rows.count() > n:
        count = await rows.count()
        await remove_btn.click()
        await expect(rows).to_have_count(count - 1, timeout=10000)


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


async def write_1(page, peers):
    await page.locator("#stepTitle").filter(
        has_text="아침에 정한 강점 행동을 돌아봅니다").wait_for(state="visible", timeout=30000)
    print("[INFO] Write_1")
    await page.locator("#closeStatus-done").check()
    await page.locator("#strengthEffort").fill(pick(DATA / 'close_effort.csv')[0])
    await page.locator("#selfNote").fill(pick(DATA / 'close_note.csv')[0])
    await page.locator("#nextBtn").click()
    await write_2(page, peers)


async def write_2(page, peers):
    await page.locator("#stepTitle").filter(
        has_text="오늘 감사했던 일을 동료들과 나눕니다").wait_for(state="visible", timeout=30000)
    print("[INFO] Write_2")
    print("입력 대상:", peers)
    await page.locator("#myShare").fill(pick(DATA / 'close_share.csv')[0])

    rows = page.locator('[id^="close-peer-story-"]')
    await set_row_count(
        page, rows,
        page.locator("#closePeerAddRow"),
        page.locator(".recognition-given-row .recognition-row-remove").last,
        len(peers),
    )

    stories = pick(DATA / 'close_peer_story.csv', len(peers))
    for i, person in enumerate(peers):
        await page.locator(f"#close-peer-{i}").fill(person)
        await page.locator(f"#close-peer-story-{i}").fill(stories[i])

    await page.locator("#nextBtn").click()
    await write_final(page, peers)


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

    events = pick(DATA / 'close_gratitude.csv', len(peers))
    for i, person in enumerate(peers):
        await page.locator(f"#gratitude-event-{i}").fill(events[i])
        await page.locator(f"#gratitude-person-{i}").fill(person)
