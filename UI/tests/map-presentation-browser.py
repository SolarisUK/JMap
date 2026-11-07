"""Check the compact, focused-label network presentation using offline data.

Run: python UI/tests/map-presentation-browser.py
No files outside UI are created or changed by this test.
"""
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
PAGE_URL = (Path(__file__).resolve().parents[1] / "operations.html").as_uri()


def ready(page):
    page.wait_for_function("!document.querySelector('#export-transfers').disabled", timeout=20000)
    assert page.locator("#error-banner").is_hidden(), page.locator("#error-message").inner_text()


def visible_items(page, selector):
    return page.locator(selector).evaluate_all("""elements=>elements.filter(element=>{
      const style=getComputedStyle(element),box=element.getBoundingClientRect();
      return style.visibility!=='hidden'&&style.display!=='none'&&box.width>0&&box.height>0;
    }).map(element=>({id:element.dataset.edgeId||element.dataset.zoneId||element.closest('[data-zone-id]')?.dataset.zoneId||element.closest('[data-edge-id]')?.dataset.edgeId,
      text:element.textContent,box:element.getBoundingClientRect().toJSON()}))""")


def positive_shortage_fixture(page):
    page.add_init_script("""(() => {
      let bundle;
      Object.defineProperty(window,'JMAP_SIMULATION_STUBS',{configurable:true,get:()=>bundle,set:value=>{
        bundle=value;
        for(const strategies of Object.values(bundle.states))
          for(const frames of Object.values(strategies))
            for(const frame of frames)
              Object.values(frame.zones).forEach((zone,index)=>{zone.unserved_mw=100+index*70;});
      }});
    })();""")


def overlaps(a, b):
    return min(a["right"], b["right"])-max(a["left"], b["left"]) > .5 and min(a["bottom"], b["bottom"])-max(a["top"], b["top"]) > .5


def map_layout(page, map_id, check_focused=True):
    bounds = page.locator(map_id).bounding_box()
    labels = visible_items(page, map_id+" .simulation-zone-id")
    assert len(labels) == 10, (map_id, "visible zone IDs", len(labels))
    focused = visible_items(page, map_id+" .simulation-transfer-label")
    assert len(focused) <= 1, (map_id, "only one focused numeric route label", focused)
    items = labels + focused if check_focused else labels
    for item in items:
        box = item["box"]
        assert box["left"] >= bounds["x"]-.5 and box["right"] <= bounds["x"]+bounds["width"]+.5, (map_id, item["id"], "horizontal clipping", box, bounds)
        assert box["top"] >= bounds["y"]-.5 and box["bottom"] <= bounds["y"]+bounds["height"]+.5, (map_id, item["id"], "vertical clipping", box, bounds)
    for index, item in enumerate(items):
        for other in items[index+1:]:
            assert not overlaps(item["box"], other["box"]), (map_id, "overlap", item["id"], other["id"])


def route_point(route):
    return route.evaluate("""element=>{
      const path=element.querySelector('path[stroke="transparent"]')||element.querySelector('path');
      const point=path.getPointAtLength(path.getTotalLength()/2).matrixTransform(path.getScreenCTM());
      return {x:point.x,y:point.y};
    }""")


def run():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        positive_shortage_fixture(page)
        page.goto(PAGE_URL)
        ready(page)
        assert page.locator("#transfer-zone-detail").is_hidden(), "Default sidebar should show the network, not a preselected zone card"
        assert page.locator("#zone").input_value() == "", "All zones is the default transfer focus"

        for map_id in ["#baseline-map", "#response-map"]:
            assert visible_items(page, map_id+" .simulation-transfer-label") == [], "Numeric route values must stay hidden until inspection"
            assert visible_items(page, map_id+" .simulation-zone-label rect") == [], "Zone labels must not be floating fact cards"
            assert page.locator(map_id+" circle.simulation-zone-node").count() == 10
            assert sorted(page.locator(map_id+" .simulation-zone-id").all_text_contents()) == sorted(page.evaluate("JMAP_SIMULATION_STUBS.reference.zone_order"))
            assert all("MW" not in item["text"] and "unserved" not in item["text"].lower() for item in visible_items(page, map_id+" .simulation-zone-label text"))
            assert visible_items(page, map_id+" .simulation-transfer-leaders path") == []
            colours = page.locator(map_id+" .simulation-zone-node").evaluate_all("nodes=>nodes.map(node=>getComputedStyle(node).fill)")
            assert len(set(colours)) > 1, "Shortage severity must remain visible in node colour"
            map_layout(page, map_id)
        print("PASS ten simultaneous shortages use compact coloured nodes/IDs and zero always-on numeric cards")

        page.locator("#zone").select_option("MIDL")
        assert page.locator("#transfer-zone-detail").is_visible()
        for map_id in ["#baseline-map", "#response-map"]:
            assert page.locator(map_id+' .simulation-zone-label[data-zone-id="MIDL"]').get_attribute("aria-pressed") == "true"
            assert visible_items(page, map_id+" .simulation-transfer-label") == []
        page.locator("#clear-map-selection").click()
        print("PASS explicit zone selection highlights both nodes and shows facts only in sidebar")

        route = page.locator('#response-map .simulation-edge[data-edge-id="NSCO-SSCO"]')
        point = route_point(route)
        page.mouse.move(point["x"], point["y"])
        assert len(visible_items(page, "#response-map .simulation-transfer-label")) == 1
        assert page.locator("#transfer-edge-detail").is_hidden(), "Hover must preview rather than change sidebar selection"
        page.mouse.move(10, 10)
        assert visible_items(page, "#response-map .simulation-transfer-label") == []
        route.focus()
        assert len(visible_items(page, "#response-map .simulation-transfer-label")) == 1
        page.locator("#zone").focus()
        assert visible_items(page, "#response-map .simulation-transfer-label") == []
        page.mouse.click(point["x"], point["y"])
        assert "NSCO-SSCO" in page.locator("#transfer-edge-title").inner_text()
        assert page.locator("#transfer-edge-detail").is_visible()
        page.mouse.move(10, 10)
        assert len(visible_items(page, "#response-map .simulation-transfer-label")) == 1, "Selected corridor value must remain pinned"
        print("PASS hover/focus preview clears, route click selects sidebar and pins one value")

        other = page.locator('#response-map .simulation-edge[data-edge-id="MIDL-EAST"]')
        other.focus()
        other.press("Enter")
        assert "MIDL-EAST" in page.locator("#transfer-edge-title").inner_text()
        for map_id in ["#baseline-map", "#response-map"]:
            assert len(visible_items(page, map_id+" .simulation-transfer-label")) == 1
            assert visible_items(page, map_id+" .simulation-transfer-label")[0]["id"] == "MIDL-EAST"
        print("PASS keyboard route activation reuses the one-value presentation and sidebar")

        for width, height in [(390, 844), (1366, 900), (1440, 900), (1366, 620), (1024, 600)]:
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(80)
            page.mouse.move(10, 10)
            for map_id in ["#baseline-map", "#response-map"]:
                try:
                    map_layout(page, map_id)
                except AssertionError as error:
                    raise AssertionError((width, height, map_id, str(error))) from error
            dimensions = page.evaluate("({width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight})")
            assert dimensions["scrollWidth"] <= width+1, dimensions
            if width >= 850:
                assert dimensions["scrollHeight"] <= height+1, dimensions
        print("PASS 390/1366/1440 and short desktop layouts: all zone IDs/focused values inside map bounds with zero overlaps")

        page.locator("#clear-map-selection").click()
        assert page.locator("#transfer-edge-detail").is_hidden()
        assert page.locator("#transfer-zone-detail").is_hidden()
        for map_id in ["#baseline-map", "#response-map"]:
            assert visible_items(page, map_id+" .simulation-transfer-label") == []
        other.focus()
        other.press("Enter")
        other.press("Escape")
        assert page.locator("#transfer-edge-detail").is_hidden()
        assert page.locator("#transfer-zone-detail").is_hidden()
        print("PASS clear and Escape restore uncluttered network overview")
        assert not errors, errors
        browser.close()


if __name__ == "__main__":
    run()
