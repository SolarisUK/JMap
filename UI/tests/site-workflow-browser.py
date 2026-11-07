"""Offline browser regressions for shared navigation and map workflows.

Run: python -B UI/tests/site-workflow-browser.py
Only local file URLs and an intercepted, coherent Elexon interval are used.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
UI = Path(__file__).resolve().parents[1]
NAV = ["generation.html", "transfers.html", "explorer.html", "operations.html"]
PAGES = {
    "generation.html": {"map": "#generation-map", "ready": "!document.querySelector('#export-sites').disabled"},
    "transfers.html": {"map": "#transfer-map", "ready": "document.querySelector('#coverage-value').textContent.includes('10')"},
    "explorer.html": {"map": "#energy-map", "ready": "document.querySelectorAll('.map-region').length>300"},
    "operations.html": {"map": "#response-map", "ready": "!document.querySelector('#export-transfers').disabled"},
}


def fuel_payload():
    now = datetime.now(timezone.utc)
    start = now.replace(minute=now.minute // 5 * 5, second=0, microsecond=0) - timedelta(minutes=5)
    codes = ["CCGT", "OCGT", "NUCLEAR", "WIND", "NPSHYD", "PS", "BIOMASS", "OTHER", "COAL", "OIL"]
    links = ["INTFR", "INTIFA2", "INTELEC", "INTNED", "INTNEM", "INTNSL", "INTVKL", "INTIRL", "INTEW", "INTGRNL"]
    return {"data": [{"dataset": "FUELINST", "fuelType": code, "generation": 200 if index % 2 == 0 else -100,
                      "startTime": start.isoformat(), "publishTime": (start + timedelta(minutes=5)).isoformat()}
                     for index, code in enumerate(codes + links)]}


def camera(page, selector):
    return page.locator(selector).evaluate("""element=>{
      const matrix=element.querySelector('path').getCTM();
      return [matrix.a,matrix.b,matrix.c,matrix.d,matrix.e,matrix.f].map(value=>+value.toFixed(6));
    }""")


def point_on_route(locator):
    return locator.evaluate("""element=>{
      const path=element.matches('path')?element:element.querySelector('.route-hit,path[stroke="transparent"],path');
      const point=path.getPointAtLength(path.getTotalLength()*.5).matrixTransform(path.getScreenCTM());
      return {x:point.x,y:point.y};
    }""")


def centre(locator):
    box = locator.bounding_box()
    assert box
    return {"x": box["x"] + box["width"] / 2, "y": box["y"] + box["height"] / 2}


def pan(page, selector, start=None):
    box = page.locator(selector).bounding_box()
    assert box
    start = start or {"x": box["x"] + box["width"] * .55, "y": box["y"] + box["height"] * .45}
    dx = 55 if start["x"] + 75 < box["x"] + box["width"] else -55
    dy = 24 if start["y"] + 40 < box["y"] + box["height"] else -24
    page.evaluate("getSelection().removeAllRanges()")
    before = camera(page, selector)
    page.mouse.move(start["x"], start["y"])
    page.mouse.down()
    page.mouse.move(start["x"] + dx, start["y"] + dy, steps=8)
    assert page.evaluate("getSelection().toString()") == "", "Map dragging must not create text selection"
    page.mouse.up()
    page.wait_for_timeout(40)
    assert camera(page, selector) != before, "Dragging must move the map"
    assert page.evaluate("getSelection().toString()") == ""


def check_navigation(page, filename, width):
    links = page.locator('nav[aria-label="Main navigation"] a:visible')
    assert links.evaluate_all("items=>items.map(item=>item.getAttribute('href'))") == NAV
    active = page.locator('nav a[aria-current="page"]')
    assert active.count() == 1 and active.get_attribute("href") == filename
    labels = [label.strip() for label in links.all_inner_texts()]
    assert labels == (["Sites", "Transfers", "Context", "Simulation"] if width < 600 else
                      ["Generation map", "Live transfers", "Energy context", "Simulation"]), labels
    assert abs(page.locator("header").bounding_box()["height"] - 40) <= 1
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"), (filename, width, "horizontal overflow")


def check_map_input(page, selector):
    page.locator("#reset-map").click()
    initial = camera(page, selector)
    page.locator(selector).focus()
    page.keyboard.press("ArrowRight")
    assert camera(page, selector) != initial, "The focused map should accept keyboard panning"
    page.keyboard.press("Home")
    assert camera(page, selector) == initial, "Home should restore the map"
    for modifier in ("ctrlKey", "metaKey"):
        result = page.locator(selector).evaluate("""(element,modifier)=>{
          const box=element.getBoundingClientRect();
          const event=new WheelEvent('wheel',{bubbles:true,cancelable:true,deltaY:-100,
            clientX:box.x+box.width/2,clientY:box.y+box.height/2,[modifier]:true});
          element.dispatchEvent(event); return event.defaultPrevented;
        }""", modifier)
        assert not result, f"{modifier}+wheel must remain available to the browser"
        assert camera(page, selector) == initial, "Browser zoom gestures must not also zoom the map"
    page.locator("#zoom-in").click()
    assert camera(page, selector) != initial
    page.locator("#reset-map").click()
    assert camera(page, selector) == initial
    # A real user can still select content outside the map after panning.
    page.locator("h1:visible,h2:visible").first.dblclick()
    assert page.evaluate("getSelection().toString().length") > 0, "Text outside maps should remain selectable"
    page.evaluate("getSelection().removeAllRanges()")


def check_interrupted_drag(page, selector):
    """Losing capture must end the gesture, rather than leave a stuck pan."""
    box = page.locator(selector).bounding_box()
    start = {"x": box["x"] + box["width"] * .5, "y": box["y"] + box["height"] * .4}
    page.locator(selector).evaluate("element=>element.addEventListener('pointerdown',event=>element.dataset.qaPointer=event.pointerId,{once:true})")
    page.mouse.move(start["x"], start["y"])
    page.mouse.down()
    page.mouse.move(start["x"] + 14, start["y"] + 9, steps=3)
    page.locator(selector).evaluate("element=>{const id=+element.dataset.qaPointer;if(element.hasPointerCapture(id))element.releasePointerCapture(id);}")
    page.wait_for_timeout(40)
    stopped = camera(page, selector)
    page.mouse.move(start["x"] + 55, start["y"] + 25, steps=4)
    page.wait_for_timeout(40)
    assert camera(page, selector) == stopped, "Lost pointer capture must cancel map movement"
    page.mouse.up()
    page.locator("#reset-map").click()


def check_live_labels(page, allow_empty=False):
    values = page.locator("#transfer-map .route-label:visible,#transfer-map .country-label:visible,#transfer-map .sea-label:visible").evaluate_all("""items=>items.map(item=>{
      const box=item.getBoundingClientRect(),matrix=item.getScreenCTM();
      return {text:item.textContent,font:parseFloat(getComputedStyle(item).fontSize)*Math.hypot(matrix.a,matrix.b),
        left:box.left,right:box.right,top:box.top,bottom:box.bottom};
    })""")
    assert values or allow_empty, "The fitted live map should expose readable labels"
    bounds = page.locator("#transfer-map").bounding_box()
    for item in values:
        assert item["font"] <= 16.1, item
        assert item["left"] >= bounds["x"] - 1 and item["right"] <= bounds["x"] + bounds["width"] + 1, item
        assert item["top"] >= bounds["y"] - 1 and item["bottom"] <= bounds["y"] + bounds["height"] + 1, item


def run():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        payload = json.dumps(fuel_payload())
        external = []

        def intercept(route):
            if "/datasets/FUELINST?" in route.request.url:
                route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=payload)
            else:
                external.append(route.request.url)
                route.abort("blockedbyclient")

        context.route("https://**/*", intercept)
        context.route("http://**/*", intercept)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        for index, (filename, config) in enumerate(PAGES.items()):
            if index == 0:
                page.goto((UI / filename).as_uri())
            else:
                page.locator(f'nav[aria-label="Main navigation"] a[href="{filename}"]').click()
                page.wait_for_url((UI / filename).as_uri())
            page.wait_for_function(config["ready"], timeout=20000)
            selector = config["map"]
            check_navigation(page, filename, 1440)
            check_map_input(page, selector)
            check_interrupted_drag(page, selector)

            if filename == "generation.html":
                assert page.locator('#generation-map').get_attribute('data-mode') == 'overview'
                assert page.locator('.generation-region').count() == 13
                row = page.locator('#overview-list [data-region-id="scotland"]')
                row.focus()
                row.press('Enter')
                assert page.locator('#generation-map').evaluate('element=>document.activeElement===element')
                assert page.locator('#overview-scope-chip').is_visible()
                page.locator('#reset-map').click()
                assert page.locator('#generation-map').get_attribute('data-mode') == 'overview'
                page.locator('#sites-view').click()
                cluster = page.locator(".generation-cluster").first
                pan(page, selector, centre(cluster))
                assert page.locator("#site-detail").is_hidden() and page.locator("#clear-cluster").is_hidden()
                page.locator("#reset-map").click()
                page.locator('#sites-view').click()
                page.locator(".generation-cluster").first.focus()
                page.keyboard.press("Enter")
                assert page.locator("#clear-cluster").is_visible()
                assert page.locator('#generation-map').evaluate('element=>document.activeElement===element')
                page.locator("#clear-cluster").click()
                page.locator("#reset-map").click()
                before = camera(page, selector)
                name = page.evaluate("JMAP_GENERATION_SITES.sites.find(site=>site.name==='Pembroke')?.name||JMAP_GENERATION_SITES.sites[0].name")
                page.locator("#site-search").fill(name)
                page.locator("#site-search").press("Home")
                page.wait_for_timeout(220)
                assert camera(page, selector) == before, "Editing search must not pan the map"
                page.locator("#site-search").press("Enter")
                page.wait_for_timeout(50)
                assert page.locator("#site-list .site-row").count() > 0
                page.locator("#site-list .site-row").first.click()
                assert page.locator("#site-detail").is_visible()
                assert "Unavailable" in page.locator("#detail-facts").inner_text()
                chosen_id = page.locator("#site-list .site-row").first.get_attribute("data-site-id")
                page.locator("#clear-site").click()
                marker = page.locator(f'.generation-marker[data-site-id="{chosen_id}"] .generation-bubble')
                pan(page, selector, centre(marker))
                assert page.locator("#site-detail").is_hidden(), "Dragging a site must not open its details"
                page.locator("#reset-filters").click()
                page.locator('#sites-view').click()
                page.locator("#country").select_option("Scotland")
                page.wait_for_timeout(80)
                visible_count = int(page.locator("#map-view-status").inner_text().split(" sites")[0].replace(",", ""))
                assert visible_count > 0, "A committed country filter must bring its matching sites into view"
            elif filename == "transfers.html":
                selected = page.locator("#detail-code").inner_text()
                route = page.locator('.route[data-link="INTFR"]')
                pan(page, selector, point_on_route(route))
                assert page.locator("#detail-code").inner_text() == selected, "Dragging a route must not select it"
                page.locator("#reset-map").click()
                route.focus()
                route.press("Enter")
                assert page.locator("#detail-code").inner_text() == "INTFR"
                for _ in range(9):
                    page.locator("#zoom-in").click()
                    check_live_labels(page, allow_empty=True)
                page.locator("#reset-map").click()
                check_live_labels(page)
            elif filename == "explorer.html":
                page.locator(selector).focus()
                page.keyboard.press("/")
                assert page.locator("#area-search").evaluate("e=>e===document.activeElement")
                assert page.locator('[data-layer="heatmap"]').get_attribute("aria-pressed") == "true", "Search shortcut must preserve the annual data layer"
                page.locator("#geography-level").select_option("nations")
                label = page.locator('.map-region-label[data-region-key="england"]')
                pan(page, selector, centre(label))
                assert page.locator("#clear-area-selection").is_hidden(), "Dragging a nation label must not select it"
                page.locator("#reset-map").click()
                label.focus()
                label.press("Enter")
                assert page.locator("#clear-area-selection").is_visible()
                label.press("Escape")
                assert page.locator("#clear-area-selection").is_hidden(), "Escape must clear context-map selection"
            else:
                route = page.locator('#response-map .simulation-edge[data-edge-id="NSCO-SSCO"]')
                pan(page, selector, point_on_route(route))
                assert page.locator("#transfer-edge-detail").is_hidden() and page.locator("#transfer-zone-detail").is_hidden()
                page.locator("#reset-map").click()
                route.focus()
                route.press("Enter")
                assert page.locator("#transfer-edge-detail").is_visible()
                before = camera(page, selector)
                page.locator("#open-incidents").click()
                page.locator("#incident-start").focus()
                page.locator("#incident-start").press("ArrowUp")
                assert camera(page, selector) == before, "Editing incident input must not pan the map"
                page.locator('[data-close="incident-dialog"]').click()

            for width, height in [(320, 740), (390, 844), (1366, 768), (1440, 900)]:
                page.set_viewport_size({"width": width, "height": height})
                page.wait_for_timeout(60)
                check_navigation(page, filename, width)
            print(f"PASS {filename}: navigation, no-selection pan, keyboard/zoom reset, focused detail and responsive shell")

        assert not external, external
        assert not errors, errors
        print("PASS all four workflows using local assets and one coherent mocked national observation")
        browser.close()


if __name__ == "__main__":
    run()
