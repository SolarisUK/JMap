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


def click_boundary(page, region):
    page.locator('#energy-map').evaluate("e=>e.scrollIntoView({block:'center'})")
    # Click inside the actual polygon, avoiding islands' empty bounding-box space
    # and the selected-area label. A ranking-list click misses native SVG focus.
    point = region.evaluate('''element=>{
      const box=element.getBBox(),matrix=element.getScreenCTM();
      for(let y=.05;y<1;y+=.05)for(let x=.05;x<1;x+=.05){
        const local=new DOMPoint(box.x+box.width*x,box.y+box.height*y);
        if(!element.isPointInFill(local))continue;
        const screen=local.matrixTransform(matrix);
        if(document.elementFromPoint(screen.x,screen.y)===element)return {x:screen.x,y:screen.y};
      }
      return null;
    }''')
    assert point, 'No visible point inside the area boundary'
    page.mouse.click(point['x'],point['y'])


def run():
    with sync_playwright() as playwright:
        # Use the full Chrome engine, not just the headless shell, and exercise
        # fractional Windows display scaling as well as high-DPI mobile output.
        browser = playwright.chromium.launch(channel='chromium')
        for width, height, dpr in [(1510, 820, 1), (1510, 820, 1.25), (390, 844, 2)]:
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=dpr)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto((UI/'explorer.html').as_uri())
            page.wait_for_function("document.querySelectorAll('.map-region').length>300")
            cases = page.evaluate("JMAP_LOCAL_AREAS.features.filter(area=>['Highland','Argyll and Bute','Cornwall','North Yorkshire'].includes(area.name)).map(({key,name})=>({key,name}))")
            assert len(cases) == 4, cases
            expected = fills(page)
            for area in cases:
                page.locator('#reset-map').click()
                page.wait_for_function("!document.querySelector('[data-camera-moving]')")
                region = page.locator(f'.map-region[data-region-key="{area["key"]}"]')
                click_boundary(page,region)
                assert region.get_attribute('aria-pressed') == 'true'
                assert fills(page) == expected, 'Selection must preserve every data colour'
                painted_map(page)
                page.locator('#zoom-regional-selection').click()
                assert region.evaluate('element=>element.getBBox().width') > 1, 'Boundary geometry must not use tiny radian units'
                region.focus()
                region.press('Enter')
                assert region.evaluate('element=>getComputedStyle(element).filter') == 'none', 'Projected boundaries must not use a glow filter'
                assert region.evaluate('element=>getComputedStyle(element).stroke') == 'rgb(222, 222, 222)', 'Keyboard focus needs a visible outline'
                assert fills(page) == expected
                assert page.locator('#energy-map > rect').first.evaluate('element=>getComputedStyle(element).fill') == 'rgb(8, 8, 8)'
                painted_map(page)
                if area['name'] == 'Highland':
                    for control in ('#zoom-in','#zoom-in','#zoom-out'):
                        page.locator(control).click()
                        page.wait_for_timeout(40)
                        painted_map(page)
                    page.wait_for_function("!document.querySelector('[data-camera-moving]')")
                    box = page.locator('#energy-map').bounding_box()
                    page.mouse.move(box['x']+box['width']*.5,box['y']+box['height']*.5)
                    page.mouse.down()
                    page.mouse.move(box['x']+box['width']*.5+35,box['y']+box['height']*.5+25,steps=6)
                    page.mouse.up()
                    painted_map(page)
                page.locator(f'.regional-ranking-row[data-ranking-nation="{area["key"]}"]').click()
                painted_map(page)
            assert not errors, errors
            print(f'PASS Chrome {width}px DPR {dpr}: complex boundaries retain dark basemap/data colours after direct clicks, list selection, zoom, pan and keyboard focus')
            page.close()
        browser.close()


if __name__ == '__main__':
    run()
