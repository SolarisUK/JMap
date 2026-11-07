"""Record the spec's backup demo against a running API (requires Playwright)."""
import argparse
from pathlib import Path
import tempfile
from playwright.sync_api import sync_playwright


def ready(page):
    page.wait_for_function("!document.querySelector('#play').disabled && document.querySelector('#frame-time').textContent.trim().length > 3", timeout=60000)
    if page.locator('#error-banner').is_visible():
        raise RuntimeError(page.locator('#error-message').text_content())


def seek(page, value):
    page.locator('#time-step').evaluate('(el,value)=>{el.value=value;el.dispatchEvent(new Event("input",{bubbles:true}))}', value)
    page.wait_for_timeout(600)


parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://127.0.0.1:8000')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
output = root / 'artifacts' / 'backup-demo.webm'
output.parent.mkdir(exist_ok=True)
recording = tempfile.mkdtemp(prefix='jmap-demo-')
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, slow_mo=160)
    context = browser.new_context(viewport={'width':1440,'height':900}, record_video_dir=recording, record_video_size={'width':1440,'height':900})
    page = context.new_page()
    page.goto(args.base_url.rstrip('/') + '/UI/operations.html')
    ready(page)
    page.wait_for_timeout(1600)
    page.click('#open-notes')
    page.wait_for_timeout(2400)
    page.click('[data-close="notes-dialog"]')
    page.select_option('#strategy','optimiser')
    ready(page)
    seek(page,0)
    page.click('#play')
    page.wait_for_timeout(2800)
    page.click('#play')
    seek(page,38)
    page.locator('#response-map .simulation-edge[data-edge-id="SSCO-NORT"]').focus()
    page.keyboard.press('Enter')
    page.wait_for_timeout(1800)
    page.click('[data-tab="forecast"]')
    page.select_option('#zone','LOND')
    page.wait_for_timeout(2200)
    page.select_option('#scenario','cold_snap')
    ready(page)
    seek(page,34)
    page.wait_for_timeout(1800)
    page.select_option('#scenario','nuclear_outage_low_wind')
    ready(page)
    seek(page,34)
    page.click('[data-tab="results"]')
    page.wait_for_timeout(2400)
    page.select_option('#scenario','b6_trip_windy_peak')
    ready(page)
    page.click('#open-incidents')
    page.fill('#incident-start','34')
    page.fill('#incident-duration','14')
    page.wait_for_timeout(1400)
    page.click('[data-preset="boundary"]')
    page.wait_for_function('!document.querySelector("#incident-dialog").open', timeout=60000)
    ready(page)
    seek(page,38)
    page.click('[data-tab="inspect"]')
    page.locator('#response-map .simulation-edge[data-edge-id="SSCO-NORT"]').focus()
    page.keyboard.press('Enter')
    page.wait_for_timeout(2000)
    page.click('[data-tab="results"]')
    page.wait_for_timeout(3000)
    page.select_option('#strategy','agents')
    ready(page)
    page.wait_for_timeout(1800)
    video = page.video
    context.close()
    video.save_as(str(output))
    browser.close()
print(f'Backup demo recorded: {output} ({output.stat().st_size:,} bytes)')
