"""Offline checks for camera easing, signed direction and motion lifecycle.

Run: python -B UI/tests/motion-browser.py
"""
import importlib.util
import json
from pathlib import Path
import unittest

from playwright.sync_api import sync_playwright

UI = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('live_tests', UI / 'tests/live-transfers-browser.py')
live_tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live_tests)


def positions(locator, simulation=False):
    return locator.evaluate('''(group,simulation)=>{
      const path=simulation?group.querySelectorAll('path')[1]:group.querySelector('.route-path');
      const length=path.getTotalLength();
      const markers=[...group.querySelectorAll(simulation?'.simulation-flow-particle':'.flow-chevron')];
      return {length,points:markers.map(marker=>{
        const m=marker.transform.baseVal.consolidate().matrix;
        let at=0,best=Infinity;
        for(let i=0;i<=2000;i++){
          const d=length*i/2000,p=path.getPointAtLength(d),error=Math.hypot(p.x-m.e,p.y-m.f);
          if(error<best){best=error;at=d;}
        }
        return at;
      })};
    }''', simulation)


class MotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 900}, reduced_motion='no-preference')
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.sign = 1
        self.partial = False

        def respond(route):
            payload = live_tests.fixture(self.partial)
            for row in payload['data']:
                if row['fuelType'] == 'INTNSL':
                    row['generation'] *= self.sign
            route.fulfill(status=200, content_type='application/json',
                          headers={'Access-Control-Allow-Origin': '*'}, body=json.dumps(payload))
        self.page.route('https://data.elexon.co.uk/**', respond)

    def tearDown(self):
        self.assertEqual(self.errors, [])
        self.context.close()

    def open(self, filename):
        self.page.goto((UI / filename).as_uri())
        if filename == 'transfers.html':
            self.page.wait_for_function("!document.querySelector('#refresh').disabled")
            self.page.wait_for_selector('#transfer-map[data-flow-moving]')
        elif filename == 'operations.html':
            self.page.wait_for_function("!document.querySelector('#export-transfers').disabled")
        elif filename == 'generation.html':
            self.page.wait_for_function("!document.querySelector('#export-sites').disabled")

    def assert_direction(self, group, reverse, simulation=False):
        before = positions(group, simulation)
        self.page.wait_for_timeout(170)
        after = positions(group, simulation)
        self.assertTrue(before['points'])
        deltas = [(end-start+before['length']/2) % before['length']-before['length']/2
                  for start, end in zip(before['points'], after['points'])]
        # At least one marker stays clear of an end fade/wrap during this sample.
        self.assertTrue(any(-15 < delta < -2 if reverse else 2 < delta < 15 for delta in deltas), deltas)

    def test_live_arrows_follow_import_then_export_and_never_zero_or_unknown(self):
        self.open('transfers.html')
        group = self.page.locator('.route[data-link=INTNSL]')
        self.assert_direction(group, reverse=True)  # route path runs GB -> Norway
        self.assertEqual(self.page.locator('.route.idle .flow-chevron,.route.unknown .flow-chevron').count(), 0)
        self.sign = -1
        self.page.locator('#refresh').click()
        self.page.wait_for_function("!document.querySelector('#refresh').disabled")
        self.assertIn('Exporting from GB', self.page.locator('#detail-direction').inner_text())
        self.assert_direction(group, reverse=False)
        self.partial = True
        self.page.locator('#refresh').click()
        self.page.wait_for_function("!document.querySelector('#refresh').disabled")
        self.assertEqual(self.page.locator('.route.unknown').count(), 9)
        self.assertEqual(self.page.locator('.route.unknown .flow-chevron').count(), 0)

    def test_pause_reduced_motion_and_page_lifecycle_stop_and_resume(self):
        self.open('transfers.html')
        group = self.page.locator('.route[data-link=INTNSL]')
        self.page.locator('#open-method').click()
        self.page.locator('#animate-live-transfers').uncheck()
        self.page.locator('#close-method').click()
        self.assertFalse(self.page.locator('#transfer-map').evaluate("e=>e.hasAttribute('data-flow-moving')"))
        resting = positions(group)
        self.page.wait_for_timeout(180)
        self.assertEqual(resting, positions(group))
        self.page.locator('#open-method').click()
        self.page.locator('#animate-live-transfers').check()
        self.page.locator('#close-method').click()
        self.assert_direction(group, reverse=True)
        self.page.emulate_media(reduced_motion='reduce')
        self.page.wait_for_function("!document.querySelector('#transfer-map').hasAttribute('data-flow-moving')")
        resting = positions(group)
        self.page.wait_for_timeout(180)
        self.assertEqual(resting, positions(group))
        self.assertGreater(self.page.locator('.flow-chevron').count(), 0)
        self.page.emulate_media(reduced_motion='no-preference')
        self.page.wait_for_selector('#transfer-map[data-flow-moving]')
        self.page.evaluate("dispatchEvent(new PageTransitionEvent('pagehide'))")
        resting = positions(group)
        self.page.wait_for_timeout(180)
        self.assertEqual(resting, positions(group))
        self.page.evaluate("dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))")
        self.page.wait_for_selector('#transfer-map[data-flow-moving]')
        self.assert_direction(group, reverse=True)
        # IntersectionObserver suspends views that leave the viewport.
        self.page.locator('#transfer-map').evaluate("e=>e.style.display='none'")
        self.page.wait_for_function("!document.querySelector('#transfer-map').hasAttribute('data-flow-moving')")
        self.page.locator('#transfer-map').evaluate("e=>e.style.display=''")
        self.page.wait_for_selector('#transfer-map[data-flow-moving]')

    def test_all_maps_ease_zoom_and_finish_immediately_when_motion_is_reduced(self):
        for filename, selector in [('generation.html', '#generation-map'), ('transfers.html', '#transfer-map'),
                                   ('explorer.html', '#energy-map'), ('operations.html', '#response-map')]:
            with self.subTest(filename=filename):
                self.page.emulate_media(reduced_motion='no-preference')
                self.open(filename)
                scale = lambda: self.page.locator(selector).evaluate("e=>e.querySelector('path').getCTM().a")
                before = scale()
                # Sample inside the browser's frames, avoiding automation
                # round-trip timing when other browser suites run alongside us.
                samples = self.page.evaluate('''selector=>new Promise(resolve=>{
                  const path=document.querySelector(selector).querySelector('path'),values=[];
                  document.querySelector('#zoom-in').click();
                  const sample=()=>{
                    values.push(path.getCTM().a);
                    if(document.querySelector('[data-camera-moving]')) requestAnimationFrame(sample);
                    else resolve(values);
                  };
                  sample();
                })''', selector)
                self.assertAlmostEqual(samples[0], before)
                self.assertGreater(samples[-1], before)
                self.assertTrue(any(before < value < samples[-1] for value in samples), samples)
                self.page.evaluate("document.querySelector('#zoom-in').click()")
                self.page.emulate_media(reduced_motion='reduce')
                self.page.wait_for_function("!document.querySelector('[data-camera-moving]')")
                self.page.evaluate("document.querySelector('#reset-map').click()")
                self.assertAlmostEqual(scale(), before, delta=.002)
                self.assertEqual(self.page.locator('[data-camera-moving],[data-flow-moving]').count(), 0)

    def test_drag_interrupts_zoom_without_rebound(self):
        self.open('transfers.html')
        self.page.evaluate("document.querySelector('#zoom-in').click()")
        self.page.wait_for_timeout(40)
        box = self.page.locator('#transfer-map').bounding_box()
        self.page.mouse.move(box['x']+80, box['y']+80)
        self.page.mouse.down()
        self.page.mouse.move(box['x']+130, box['y']+105, steps=4)
        self.page.mouse.up()
        stopped = self.page.locator('.transfer-geometry-layer').get_attribute('transform')
        self.page.wait_for_timeout(230)
        self.assertEqual(self.page.locator('.transfer-geometry-layer').get_attribute('transform'), stopped)
        self.assertEqual(self.page.evaluate('getSelection().toString()'), '')

    def test_simulation_motion_uses_signed_flow_and_obeys_saved_off_setting(self):
        self.open('operations.html')
        self.page.wait_for_selector('#response-map[data-flow-moving]')
        for reverse in (False, True):
            groups = self.page.locator(f'#response-map .simulation-edge[data-reverse="{str(reverse).lower()}"]')
            candidates = [group for group in groups.all() if group.locator('.simulation-flow-particle[display="inline"]').count()
                          and group.evaluate("e=>e.querySelectorAll('path')[1].getTotalLength()") > 70]
            self.assertTrue(candidates)
            self.assert_direction(candidates[0], reverse, simulation=True)
        self.page.emulate_media(reduced_motion='reduce')
        self.page.wait_for_function("!document.querySelector('[data-flow-moving]')")
        self.assertEqual(self.page.locator('.simulation-flow-particle:visible').count(), 0)
        self.page.emulate_media(reduced_motion='no-preference')
        self.page.wait_for_selector('#response-map[data-flow-moving]')
        self.page.locator('#open-notes').click()
        self.page.locator('#animate-transfers').uncheck()
        self.page.locator('[data-close="notes-dialog"]').click()
        self.assertIn('motion=0', self.page.url)
        self.page.reload()
        self.page.wait_for_function("!document.querySelector('#export-transfers').disabled")
        self.assertEqual(self.page.locator('[data-flow-moving]').count(), 0)

    def test_split_simulation_camera_input_can_switch_maps_mid_animation(self):
        self.open('operations.html')
        result = self.page.evaluate('''()=>new Promise(resolve=>{
          document.querySelector('#zoom-in').click();
          requestAnimationFrame(()=>{
            const baseline=document.querySelector('#baseline-map');
            baseline.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true,cancelable:true}));
            const moving=baseline.hasAttribute('data-camera-moving');
            const sample=()=>{
              if(document.querySelector('[data-camera-moving]')) {requestAnimationFrame(sample);return;}
              const matrix=id=>{
                const root=document.querySelector(id),m=root.querySelector('path').getCTM();
                return {scale:m.a,pan:m.e-root.viewBox.baseVal.width/2};
              };
              const a=matrix('#baseline-map'),b=matrix('#response-map');
              resolve({moving,scaleDifference:Math.abs(a.scale-b.scale),panDifference:Math.abs(a.pan-b.pan)});
            };
            sample();
          });
        })''')
        self.assertTrue(result['moving'])
        self.assertLess(result['scaleDifference'], .001)
        self.assertLess(result['panDifference'], .001)


if __name__ == '__main__':
    unittest.main(verbosity=2)
