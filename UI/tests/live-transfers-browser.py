"""UI-only browser regressions; no backend or network needed by default.

Run: python -B UI/tests/live-transfers-browser.py
Requires an installed Playwright Chromium. Test fixtures intercept only Elexon's
public URL; production has no fixture or stored-data fallback. Set
JMAP_LIVE_NETWORK_TEST=1 to add an actual Elexon request when network is allowed.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import unittest

from playwright.sync_api import sync_playwright

PAGE = (Path(__file__).resolve().parents[1] / "transfers.html").as_uri()
CODES = ("INTFR", "INTIFA2", "INTELEC", "INTNED", "INTNEM", "INTNSL", "INTVKL", "INTIRL", "INTEW", "INTGRNL")


def fixture(partial=False):
    now = datetime.now(timezone.utc)
    end = now.replace(minute=now.minute // 5 * 5, second=0, microsecond=0)
    start = end - timedelta(minutes=5)
    rows = [{"dataset": "FUELINST", "fuelType": code, "generation": 1400 if code == "INTNSL" else -250 if code in {"INTIRL", "INTEW", "INTGRNL"} else 0 if code == "INTNED" else 100, "startTime": start.isoformat(), "publishTime": end.isoformat()} for code in CODES]
    if partial:
        for row in rows:
            if row["fuelType"] != "INTNSL":
                row["startTime"] = (start - timedelta(minutes=5)).isoformat()
    return {"data": rows}


class TransfersBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1366, "height": 900})
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.fail = False
        self.partial = False
        self.requests = 0

        def respond(route):
            self.requests += 1
            if self.fail:
                route.abort()
            else:
                route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=json.dumps(fixture(self.partial)))
        self.page.route("https://data.elexon.co.uk/**", respond)

    def tearDown(self):
        self.assertEqual(self.errors, [])
        self.context.close()

    def open(self):
        self.page.goto(PAGE, wait_until="domcontentloaded")
        self.page.wait_for_function("!document.querySelector('#refresh').disabled", timeout=20000)

    def settle_camera(self):
        self.page.wait_for_function("!document.querySelector('[data-camera-moving]')")

    def test_signed_values_and_actual_svg_pointer_selection(self):
        self.open()
        self.assertEqual(self.page.locator("#coverage-value").inner_text(), "10 / 10")
        self.assertIn("Out of GB", self.page.locator("tr[data-link=INTEW]").inner_text())
        path = self.page.locator("g.route[data-link=INTVKL] .route-hit")
        point = path.evaluate("e=>{const p=e.getPointAtLength(e.getTotalLength()*.5),s=e.getScreenCTM();return{x:s.a*p.x+s.c*p.y+s.e,y:s.b*p.x+s.d*p.y+s.f}}")
        self.page.mouse.click(point["x"], point["y"])
        self.assertEqual(self.page.locator("#detail-code").inner_text(), "INTVKL")
        self.page.locator("g.route[data-link=INTNSL]").focus()
        self.page.keyboard.press("Enter")
        self.assertEqual(self.page.locator("#detail-code").inner_text(), "INTNSL")

    def test_partial_latest_interval_has_unknown_links_and_labelled_partial_totals(self):
        self.partial = True
        self.open()
        self.assertEqual(self.page.locator("#coverage-value").inner_text(), "1 / 10")
        self.assertIn("partial", self.page.locator("#net-label").inner_text())
        self.assertIn("Unknown", self.page.locator("tr[data-link=INTGRNL]").inner_text())
        self.assertIn("1,400", self.page.locator("#net-value").inner_text())

    def test_failed_refresh_retains_the_previous_observation_with_its_time(self):
        self.open()
        net = self.page.locator("#net-value").inner_text()
        stamp = self.page.locator("#observation-time").inner_text()
        self.fail = True
        self.page.locator("#refresh").click()
        self.page.wait_for_function("!document.querySelector('#refresh').disabled")
        self.assertEqual(self.page.locator("#net-value").inner_text(), net)
        self.assertEqual(self.page.locator("#observation-time").inner_text(), stamp)
        self.assertIn("last received observation", self.page.locator("#error-message").inner_text())
        self.assertEqual(self.page.locator("#feed-badge").inner_text(), "Update failed")

    def test_initial_failure_keeps_all_values_unknown(self):
        self.fail = True
        self.open()
        self.assertEqual(self.page.locator(".route.unknown").count(), 10)
        self.assertNotIn("0", self.page.locator("#net-value").inner_text())
        self.assertIn("No live values", self.page.locator("#error-message").inner_text())

    def test_desktop_route_labels_do_not_overlap(self):
        self.open()
        overlaps = self.page.evaluate("""()=>{const labels=[...document.querySelectorAll('.route-label')].map(e=>({name:e.textContent,r:e.getBoundingClientRect()}));return labels.flatMap((a,i)=>labels.slice(i+1).filter(b=>a.r.left<b.r.right&&a.r.right>b.r.left&&a.r.top<b.r.bottom&&a.r.bottom>b.r.top).map(b=>[a.name,b.name]));}""")
        self.assertEqual(overlaps, [])

    def test_mobile_header_and_layout_remain_compact_and_show_feed_status(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.open()
        self.assertLessEqual(self.page.locator(".app-header").bounding_box()["height"], 41)
        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth>innerWidth"))
        self.assertTrue(self.page.locator("#mobile-feed-status").is_visible())
        self.assertIn("Elexon", self.page.locator("#mobile-feed-status").inner_text())
        self.assertEqual(self.page.locator(".route-label:visible").count(), 1)

    def test_zoom_keeps_text_screen_sized_and_uses_the_same_button_and_keyboard_step(self):
        self.open()
        before = self.page.locator('.route-label-group.selected .route-label tspan').first.evaluate('e=>e.getBoundingClientRect().height')
        for _ in range(4):
            self.page.locator('#zoom-in').click()
        self.settle_camera()
        self.assertAlmostEqual(self.page.locator('.transfer-geometry-layer').evaluate('e=>e.getCTM().a'), 1.35 ** 4, places=5)
        sizes = self.page.locator('.transfer-label-layer text:visible').evaluate_all('items=>items.map(e=>parseFloat(getComputedStyle(e).fontSize)*Math.hypot(e.getScreenCTM().a,e.getScreenCTM().b))')
        self.assertTrue(sizes)
        self.assertTrue(all(9 <= size <= 14 for size in sizes))
        after = self.page.locator('.route-label-group.selected .route-label tspan').first.evaluate('e=>e.getBoundingClientRect().height')
        self.assertLessEqual(after, 16)
        self.assertAlmostEqual(after, before, delta=1)
        self.assertEqual(self.page.locator('.transfer-label-layer').evaluate('e=>e.getCTM().a'), 1)
        for _ in range(5):
            self.page.locator('#zoom-in').click()
        self.settle_camera()
        self.assertAlmostEqual(self.page.locator('.transfer-geometry-layer').evaluate('e=>e.getCTM().a'), 7, places=5)
        terminals = self.page.locator('.route .terminal').evaluate_all('items=>items.map(e=>{const r=e.getBoundingClientRect();return [r.width,r.height]})')
        arrows = self.page.locator('.flow-chevron').evaluate_all('items=>items.map(e=>{const r=e.getBoundingClientRect();return Math.max(r.width,r.height)})')
        self.assertEqual(len(terminals), 20)
        self.assertTrue(all(5 <= size <= 8 for pair in terminals for size in pair))
        self.assertTrue(arrows and all(5 <= size <= 12 for size in arrows))
        self.page.locator('#reset-map').click()
        self.settle_camera()
        self.page.locator('#transfer-map').focus()
        self.page.keyboard.press('+')
        self.settle_camera()
        self.assertAlmostEqual(self.page.locator('.transfer-geometry-layer').evaluate('e=>e.getCTM().a'), 1.35, places=5)
        self.page.keyboard.press('Home')
        self.settle_camera()
        self.assertAlmostEqual(self.page.locator('.transfer-geometry-layer').evaluate('e=>e.getCTM().a'), 1, places=5)

    def test_dragging_a_route_pans_without_activating_it_or_selecting_map_text(self):
        self.open()
        self.page.evaluate('getSelection().removeAllRanges()')
        route = self.page.locator('g.route[data-link=INTVKL] .route-hit')
        point = route.evaluate('e=>{const p=e.getPointAtLength(e.getTotalLength()*.5),s=e.getScreenCTM();return{x:s.a*p.x+s.c*p.y+s.e,y:s.b*p.x+s.d*p.y+s.f}}')
        initial = self.page.locator('.transfer-geometry-layer').get_attribute('transform')
        self.page.mouse.move(point['x'], point['y'])
        self.page.mouse.down()
        self.page.mouse.move(point['x'] + 80, point['y'] + 35, steps=5)
        self.page.mouse.up()
        self.assertNotEqual(self.page.locator('.transfer-geometry-layer').get_attribute('transform'), initial)
        self.assertEqual(self.page.locator('#detail-code').inner_text(), 'INTNSL')
        self.assertEqual(self.page.evaluate('getSelection().toString()'), '')
        self.assertFalse(self.page.locator('#transfer-map').evaluate('e=>e.classList.contains("is-panning")'))
        self.assertNotEqual(self.page.locator('h1').evaluate('e=>getComputedStyle(e).userSelect'), 'none')
        moved = route.evaluate('e=>{const p=e.getPointAtLength(e.getTotalLength()*.5),s=e.getScreenCTM();return{x:s.a*p.x+s.c*p.y+s.e,y:s.b*p.x+s.d*p.y+s.f}}')
        self.page.mouse.click(moved['x'], moved['y'])
        self.assertEqual(self.page.locator('#detail-code').inner_text(), 'INTVKL')

    def test_visible_selected_route_keeps_direction_arrows_after_old_anchors_leave_view(self):
        # This test checks the resting layout; animated marker paths are
        # checked separately in motion-browser.py.
        self.page.emulate_media(reduced_motion='reduce')
        self.open()
        for _ in range(5):
            self.page.locator('#zoom-in').click()
        result = self.page.locator('.route[data-link=INTNSL]').evaluate('''group=>{
            const map=document.querySelector('#transfer-map').getBoundingClientRect();
            const path=group.querySelector('.route-path'), length=path.getTotalLength(), matrix=path.getScreenCTM();
            const project=p=>({x:matrix.a*p.x+matrix.c*p.y+matrix.e,y:matrix.b*p.x+matrix.d*p.y+matrix.f});
            const inside=p=>p.x>=map.left&&p.x<=map.right&&p.y>=map.top&&p.y<=map.bottom;
            const labels=[...document.querySelectorAll('.route-label')].filter(e=>e.getBoundingClientRect().width).map(e=>e.getBoundingClientRect());
            return {
                oldAnchorsOutside:[.38,.60].every(f=>!inside(project(path.getPointAtLength(length*f)))),
                arrows:[...group.querySelectorAll('.flow-chevron')].map(arrow=>{
                    const r=arrow.getBoundingClientRect(), local=arrow.transform.baseVal.consolidate().matrix, m=arrow.getScreenCTM();
                    let at=0,best=Infinity;
                    for(let i=0;i<=1000;i++){const d=length*i/1000,p=path.getPointAtLength(d),distance=Math.hypot(p.x-local.e,p.y-local.f);if(distance<best){best=distance;at=d}}
                    const before=project(path.getPointAtLength(Math.max(0,at-1))),after=project(path.getPointAtLength(Math.min(length,at+1)));
                    return {
                        inside:r.left>=map.left+5&&r.right<=map.right-5&&r.top>=map.top+5&&r.bottom<=map.bottom-5,
                        size:Math.max(r.width,r.height),
                        importDirectionDot:m.a*(after.x-before.x)+m.b*(after.y-before.y),
                        overlapsLabel:labels.some(b=>r.left<b.right&&r.right>b.left&&r.top<b.bottom&&r.bottom>b.top)
                    };
                })
            };
        }''')
        self.assertTrue(result['oldAnchorsOutside'])
        self.assertTrue(1 <= len(result['arrows']) <= 2)
        for arrow in result['arrows']:
            self.assertTrue(arrow['inside'])
            self.assertTrue(5 <= arrow['size'] <= 12)
            self.assertLess(arrow['importDirectionDot'], 0)
            self.assertFalse(arrow['overlapsLabel'])

    def test_cancel_lost_capture_and_blur_end_the_active_pan(self):
        self.open()
        bounds = self.page.locator('#transfer-map').bounding_box()
        x, y = bounds['x'] + 110, bounds['y'] + 110
        for cancellation in ('pointercancel', 'lostpointercapture', 'blur'):
            self.page.mouse.move(x, y)
            self.page.mouse.down()
            self.page.mouse.move(x + 45, y + 25, steps=3)
            self.assertTrue(self.page.locator('#transfer-map').evaluate('e=>e.classList.contains("is-panning")'))
            if cancellation == 'blur':
                self.page.evaluate('dispatchEvent(new Event("blur"))')
            else:
                self.page.locator('#transfer-map').dispatch_event(cancellation, {'pointerId': 1, 'pointerType': 'mouse', 'bubbles': True})
            stopped = self.page.locator('.transfer-geometry-layer').get_attribute('transform')
            self.page.mouse.move(x + 90, y + 60, steps=3)
            self.assertEqual(self.page.locator('.transfer-geometry-layer').get_attribute('transform'), stopped)
            self.assertFalse(self.page.locator('#transfer-map').evaluate('e=>e.classList.contains("is-panning")'))
            self.page.mouse.up()

    def test_two_touch_pinch_zooms_without_selecting_a_route(self):
        self.open()
        bounds = self.page.locator('#transfer-map').bounding_box()
        x, y = bounds['x'] + bounds['width'] / 2, bounds['y'] + bounds['height'] / 2
        session = self.context.new_cdp_session(self.page)
        def touches(distance):
            return [{'x': x - distance, 'y': y, 'id': 1}, {'x': x + distance, 'y': y, 'id': 2}]
        session.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': touches(45)})
        session.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': touches(95)})
        session.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
        self.assertGreater(self.page.locator('.transfer-geometry-layer').evaluate('e=>e.getCTM().a'), 1.8)
        self.assertEqual(self.page.locator('#detail-code').inner_text(), 'INTNSL')
        self.assertFalse(self.page.locator('#transfer-map').evaluate('e=>e.classList.contains("is-panning")'))
        session.detach()

    def test_ctrl_and_meta_wheel_keep_browser_zoom_available(self):
        self.open()
        for modifier in ('ctrlKey', 'metaKey'):
            prevented = self.page.locator('#transfer-map').evaluate('(e,modifier)=>{const event=new WheelEvent("wheel",{deltaY:-120,[modifier]:true,bubbles:true,cancelable:true});e.dispatchEvent(event);return event.defaultPrevented}', modifier)
            self.assertFalse(prevented)
            self.assertAlmostEqual(self.page.locator('.transfer-geometry-layer').evaluate('e=>e.getCTM().a'), 1, places=5)
        prevented = self.page.locator('#transfer-map').evaluate('e=>{const event=new WheelEvent("wheel",{deltaY:-120,bubbles:true,cancelable:true});e.dispatchEvent(event);return event.defaultPrevented}')
        self.assertTrue(prevented)
        self.assertGreater(self.page.locator('.transfer-geometry-layer').evaluate('e=>e.getCTM().a'), 1)

    def test_page_cache_return_restarts_polling_and_refreshes(self):
        self.page.add_init_script("""window.__activeIntervals=new Set();const add=window.setInterval.bind(window),remove=window.clearInterval.bind(window);window.setInterval=(...args)=>{const id=add(...args);window.__activeIntervals.add(id);return id};window.clearInterval=id=>{window.__activeIntervals.delete(id);return remove(id)};""")
        self.open()
        before = self.requests
        self.assertEqual(self.page.evaluate("__activeIntervals.size"), 2)
        self.page.evaluate("dispatchEvent(new PageTransitionEvent('pagehide',{persisted:true}))")
        self.assertEqual(self.page.evaluate("__activeIntervals.size"), 0)
        self.page.evaluate("dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))")
        self.page.wait_for_function("!document.querySelector('#refresh').disabled")
        self.assertEqual(self.page.evaluate("__activeIntervals.size"), 2)
        self.assertGreater(self.requests, before)

    @unittest.skipUnless(os.getenv("JMAP_LIVE_NETWORK_TEST") == "1", "Actual Elexon request requires network permission")
    def test_actual_public_elexon_feed(self):
        self.page.unroute("https://data.elexon.co.uk/**")
        self.open()
        coverage = self.page.locator("#coverage-value").inner_text().split("/")[0].strip()
        self.assertTrue(coverage.isdecimal() and int(coverage) > 0)
        self.assertFalse(self.page.locator("#error-banner").is_visible())


if __name__ == "__main__":
    unittest.main(verbosity=2)
