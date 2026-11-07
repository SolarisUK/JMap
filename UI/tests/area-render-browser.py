"""Check that complex area selections keep a painted, dark map.

Run: python -B UI/tests/area-render-browser.py (Playwright, Chromium and Pillow)
Screenshots are inspected in memory; backend files are never changed.
"""
from io import BytesIO
from pathlib import Path
import sys

from PIL import Image
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
UI = Path(__file__).resolve().parents[1]


def painted_map(page):
    bitmap = Image.open(BytesIO(page.locator('#energy-map').screenshot())).convert('RGB')
    pixels = list(getattr(bitmap, 'get_flattened_data', bitmap.getdata)())
    white = sum(min(pixel) >= 245 for pixel in pixels)
    dark = sum(max(pixel) < 50 for pixel in pixels)
    blue = sum(b > r+15 and b > g+5 for r, g, b in pixels)
    assert white/len(pixels) < .03, 'Map painted white after area selection'
    assert dark/len(pixels) > .05, 'The dark basemap disappeared'
    assert blue > 100, 'Heatmap data polygons disappeared'


def fills(page):
    return page.locator('.map-region').evaluate_all('items=>Object.fromEntries(items.map(item=>[item.dataset.regionKey,getComputedStyle(item).fill]))')


def run():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width, height in [(1510, 820), (390, 844)]:
            page = browser.new_page(viewport={"width": width, "height": height})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto((UI/'explorer.html').as_uri())
            page.wait_for_function("document.querySelectorAll('.map-region').length>300")
            cases = page.evaluate("JMAP_LOCAL_AREAS.features.filter(area=>['Highland','Argyll and Bute','Cornwall','North Yorkshire'].includes(area.name)).map(({key,name})=>({key,name}))")
            assert len(cases) == 4, cases
            expected = fills(page)
            for area in cases:
                page.locator('#reset-map').click()
                region = page.locator(f'.map-region[data-region-key="{area["key"]}"]')
                page.locator(f'.regional-ranking-row[data-ranking-nation="{area["key"]}"]').click()
                assert region.get_attribute('aria-pressed') == 'true'
                assert fills(page) == expected, 'Selection must preserve every data colour'
                painted_map(page)
                page.locator('#zoom-regional-selection').click()
                region.focus()
                region.press('Enter')
                assert region.evaluate('element=>getComputedStyle(element).filter') == 'none', 'Projected boundaries must not use a glow filter'
                assert region.evaluate('element=>getComputedStyle(element).stroke') == 'rgb(222, 222, 222)', 'Keyboard focus needs a visible outline'
                assert fills(page) == expected
                assert page.locator('#energy-map > rect').first.evaluate('element=>getComputedStyle(element).fill') == 'rgb(8, 8, 8)'
                painted_map(page)
            assert not errors, errors
            print(f'PASS {width}px: Highland, Argyll and Bute, Cornwall and North Yorkshire retain dark basemap/data colours after pointer selection, zoom and keyboard selection')
            page.close()
        browser.close()


if __name__ == '__main__':
    run()
