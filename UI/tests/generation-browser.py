"""Offline UI checks for the official site catalogue and mocked national feed.

Run: python -B UI/tests/generation-browser.py
Downloads are temporary and remain beneath UI/tests.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import re
import sys
import tempfile

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
TEST_DIR = Path(__file__).resolve().parent
PAGE_URL = (TEST_DIR.parent / "generation.html").as_uri()


def ready(page):
    page.wait_for_function("document.querySelector('#site-count').textContent!=='—'&&!document.querySelector('#export-sites').disabled", timeout=20000)
    assert page.locator("#catalogue-error").is_hidden(), page.locator("#catalogue-error").inner_text()


def site_count(page):
    return int(page.locator("#site-count").inner_text().replace(",", ""))


def facts(page, selector):
    return page.locator(selector).evaluate("element=>Object.fromEntries([...element.children].map(row=>[row.querySelector('dt').textContent,row.querySelector('dd').textContent]))")


def mw(text):
    return float(text.replace(",", "").replace(" MW", ""))


def map_scale(page):
    return page.locator('.generation-land').evaluate('node=>node.transform.baseVal.consolidate().matrix.a')


def assert_mode(page, mode):
    assert page.locator('#generation-map').get_attribute('data-mode') == mode
    for key in ('overview', 'sites'):
        assert page.locator(f'#{key}-view').get_attribute('aria-pressed') == str(key == mode).lower()
    assert page.locator('#overview-panel').is_visible() == (mode == 'overview')
    assert page.locator('#site-results').is_visible() == (mode == 'sites')


def assert_no_count_glyphs(page):
    texts = page.locator('#generation-map .generation-region text:visible,#generation-map .generation-cluster text:visible').all_text_contents()
    assert not [text for text in texts if re.fullmatch(r'\s*[\d,.]+\s*[kK]?\s*', text)], texts


def export_rows(page):
    with page.expect_download() as event:
        page.locator('#export-sites').click()
    rows = list(csv.reader(io.StringIO(Path(event.value.path()).read_text(encoding='utf-8-sig'))))
    start = next(index for index, row in enumerate(rows) if row and row[0] == 'ID')
    return [dict(zip(rows[start], row)) for row in rows[start + 1:]]


def assert_sites_capacity_scale(page, zoom=1):
    result = page.locator('#generation-map').evaluate('''(element,zoom)=>{
      return [...element.querySelectorAll('.generation-marker,.generation-cluster')].map(group=>{
        const circle=group.querySelector('.generation-bubble,.generation-cluster-bubble');
        const capacity=Number(group.dataset.capacityMw);
        return {capacity,radius:Number(circle.getAttribute('r')),expected:GenerationMap.markerRadius(capacity,zoom)};
      });
    }''', zoom)
    assert result
    assert all(item['capacity'] > 0 and abs(item['radius'] - item['expected']) <= .02 for item in result), result


def blank_map_point(page):
    return page.locator('#generation-map').evaluate('''svg=>{
      const box=svg.getBoundingClientRect();
      for(let y=80;y<box.height-110;y+=45)for(let x=35;x<box.width-40;x+=55){
        const target=document.elementFromPoint(box.left+x,box.top+y);
        if(target?.closest('#generation-map')&&!target.closest('.generation-marker,.generation-cluster,.generation-region'))return {x:box.left+x,y:box.top+y};
      }
      throw new Error('No unobstructed map point available');
    }''')


def fuel_payload():
    now = datetime.now(timezone.utc)
    start = now.replace(minute=now.minute//5*5, second=0, microsecond=0)-timedelta(minutes=5)
    publish = start+timedelta(minutes=5)
    codes = ["CCGT", "OCGT", "NUCLEAR", "WIND", "NPSHYD", "PS", "BIOMASS", "OTHER", "COAL", "OIL"]
    links = ["INTFR", "INTIFA2", "INTELEC", "INTNED", "INTNEM", "INTNSL", "INTVKL", "INTIRL", "INTEW", "INTGRNL"]
    values = [(code, -50 if code == "PS" else -20 if code == "OTHER" else 100) for code in codes]+[(code, -100 if index % 2 else 200) for index, code in enumerate(links)]
    return {"data": [{"dataset": "FUELINST", "fuelType": code, "generation": value, "startTime": start.isoformat(), "publishTime": publish.isoformat()} for code, value in values]}


def run():
    with tempfile.TemporaryDirectory(prefix="generation-qa-", dir=TEST_DIR) as folder:
        download_dir = Path(folder).resolve()
        assert download_dir.is_relative_to(TEST_DIR)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, downloads_path=str(download_dir))
            context = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            fail_feed = {"value": False}
            payload = fuel_payload()

            def feed(route):
                if fail_feed["value"]:
                    route.abort("failed")
                else:
                    route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=json.dumps(payload))

            page.route("**/datasets/FUELINST?*", feed)
            page.goto(PAGE_URL)
            ready(page)
            total = page.evaluate("JMAP_GENERATION_SITES.sites.length")
            assert total > 3000
            assert site_count(page) == total
            assert page.evaluate("JMAP_GENERATION_SITES.sites.every(site=>site.sourceUrl&&site.sourceDate&&Number.isFinite(site.lat)&&Number.isFinite(site.lon))")
            assert_mode(page, 'overview')
            expected_regions = page.evaluate('JMapGenerationOverview.aggregateRegions(JMAP_GENERATION_SITES.sites).map(({id,name,capacityMW,siteCount,sites})=>({id,name,capacityMW,siteCount,ids:sites.map(site=>site.id)}))')
            assert len(expected_regions) == 13
            regions = page.locator('#generation-map .generation-region')
            assert regions.count() == 13
            assert page.locator('#generation-map .generation-marker,#generation-map .generation-cluster').count() == 0
            actual_regions = regions.evaluate_all('items=>items.map(item=>({id:item.dataset.regionId,count:Number(item.dataset.count),capacity:Number(item.dataset.capacityMw),description:item.getAttribute("aria-label")}))')
            for expected in expected_regions:
                actual = next(region for region in actual_regions if region['id'] == expected['id'])
                assert actual['description'].startswith(expected['name'] + ':')
                assert actual['count'] == expected['siteCount']
                assert abs(actual['capacity'] - expected['capacityMW']) < .00001
                row = page.locator(f'#overview-list [data-region-id="{expected["id"]}"]')
                assert row.is_visible() and expected['name'] in row.inner_text()
            assert sum(region['count'] for region in actual_regions) == total
            capacity_total = page.evaluate('JMAP_GENERATION_SITES.sites.reduce((sum,site)=>sum+site.capacityMW,0)')
            assert abs(sum(region['capacity'] for region in actual_regions) - capacity_total) < .00001
            assert_no_count_glyphs(page)
            readout = page.locator('.generation-region-readout')
            assert readout.is_hidden(), 'The overview should not start with floating region labels'
            row = page.locator('#overview-list [data-region-id="scotland"]')
            row.hover()
            assert readout.is_visible() and 'Scotland' in readout.text_content()
            assert 'GW installed' in readout.text_content()
            assert page.locator('.generation-region[data-highlighted="true"]').count() == 1
            assert page.locator('.generation-region[data-region-id="scotland"]').get_attribute('data-highlighted') == 'true'
            page.mouse.move(1, 1)
            assert readout.is_hidden()
            page.locator('.generation-region[data-region-id="scotland"]').focus()
            assert readout.is_visible() and 'Scotland' in readout.text_content()
            page.locator('#site-search').focus()
            assert readout.is_hidden()
            assert page.locator('.generation-region text,.generation-region line').count() == 0
            exported = export_rows(page)
            assert len(exported) == total
            assert {row['ID'] for row in exported} == set(page.evaluate('JMAP_GENERATION_SITES.sites.map(site=>site.id)'))
            print(f'PASS 13 named regions conserve all {total} sourced records and installed MW; complete UK export')

            scotland = next(region for region in expected_regions if region['id'] == 'scotland')
            region = page.locator('.generation-region[data-region-id="scotland"]')
            region.focus()
            region.press('Enter')
            assert_mode(page, 'sites')
            assert site_count(page) == scotland['siteCount']
            assert page.locator('#overview-scope-chip').is_visible()
            assert 'Scotland' in page.locator('#overview-scope-chip').inner_text()
            assert page.locator('#site-list .site-row').count() == min(120, scotland['siteCount'])
            assert set(page.locator('#site-list .site-row').evaluate_all('items=>items.map(item=>item.dataset.siteId)')).issubset(scotland['ids'])
            assert {row['ID'] for row in export_rows(page)} == set(scotland['ids'])
            assert_no_count_glyphs(page)
            page.locator('#overview-view').click()
            assert_mode(page, 'overview')
            assert site_count(page) == total
            assert page.locator('#overview-scope-chip').is_hidden()
            print('PASS keyboard region drill-down scopes site list, totals and export; Overview restores the UK')

            page.locator('#sites-view').click()
            assert_mode(page, 'sites')
            clusters = page.locator('#generation-map .generation-cluster')
            assert clusters.count() > 0
            represented = page.locator('.generation-cluster,.generation-marker').evaluate_all('items=>items.reduce((sum,item)=>sum+(Number(item.dataset.count)||1),0)')
            assert represented == total, 'Capacity groups must retain every catalogue site'
            mapped_capacity = page.locator('.generation-cluster,.generation-marker').evaluate_all('items=>items.reduce((sum,item)=>sum+Number(item.dataset.capacityMw),0)')
            assert abs(mapped_capacity - capacity_total) < .00001
            assert_no_count_glyphs(page)
            assert_sites_capacity_scale(page)
            old_transform = page.locator(".generation-land").get_attribute("transform")
            group_count = int(clusters.first.get_attribute("data-count"))
            clusters.first.focus()
            clusters.first.press("Enter")
            assert page.locator(".generation-land").get_attribute("transform") != old_transform
            assert site_count(page) == total
            assert page.locator("#clear-cluster").is_visible()
            assert page.locator("#site-list .site-row").count() == min(120, group_count)
            assert "Selected group" in page.locator("#site-list-title").inner_text()
            group_title = page.locator('#site-list-title').inner_text()
            page.locator('#site-list .site-row').first.click()
            assert page.locator('#site-detail').is_visible()
            blank = blank_map_point(page)
            page.mouse.click(blank['x'], blank['y'])
            assert page.locator('#site-detail').is_hidden()
            assert page.locator('#clear-cluster').is_visible()
            assert page.locator('#site-list-title').inner_text() == group_title
            page.locator("#clear-cluster").click()
            page.locator("#reset-map").click()
            assert_mode(page, 'overview')
            assert site_count(page) == total
            print('PASS Sites groups use capacity area without count glyphs; keyboard group inspection and blank-map clear remain usable')

            page.locator('#sites-view').click()
            page.locator('#site-list .site-row').first.click()
            page.locator("#country").select_option("Scotland")
            assert int(page.locator('#map-view-status').inner_text().split(' sites')[0].replace(',', '')) > 0, 'A committed country change must frame its results after an unrelated site was focused'
            page.locator("#technology").select_option("wind_onshore")
            expected = page.evaluate("JMAP_GENERATION_SITES.sites.filter(site=>site.country==='Scotland'&&site.type==='wind_onshore').length")
            assert site_count(page) == expected
            assert page.locator("#site-list .site-row").count() == min(120, expected)
            with page.expect_download() as event:
                page.locator("#export-sites").click()
            rows = list(csv.reader(io.StringIO(Path(event.value.path()).read_text(encoding="utf-8-sig"))))
            start = next(index for index, row in enumerate(rows) if row and row[0] == "ID")
            assert len(rows[start+1:]) == expected
            assert all(row[2] == "wind_onshore" and row[3] == "Scotland" for row in rows[start+1:])
            page.locator("#reset-filters").click()
            assert site_count(page) == total
            print("PASS country/type filters, true site counts and export of every match beyond the 120-row list")

            assert_mode(page, 'overview')
            page.locator('#country').select_option('Scotland')
            page.locator('#technology').select_option('wind_onshore')
            assert_mode(page, 'overview')
            assert site_count(page) == expected
            assert page.locator('.generation-region').count() == 1
            assert page.locator('.generation-region').get_attribute('data-region-id') == 'scotland'
            page.locator('#reset-map').click()
            assert_mode(page, 'overview')
            assert page.locator('#country').input_value() == 'Scotland'
            assert page.locator('#technology').input_value() == 'wind_onshore'
            assert site_count(page) == expected
            page.locator('#reset-filters').click()
            page.locator('#sites-view').click()
            first = page.locator("#site-list .site-row").first
            chosen_id = first.get_attribute("data-site-id")
            chosen = page.evaluate("id=>JMAP_GENERATION_SITES.sites.find(site=>site.id===id)", chosen_id)
            first.click()
            assert page.locator("#site-detail").is_visible()
            assert page.locator("#detail-name").inner_text() == chosen["name"]
            assert abs(mw(page.locator("#detail-capacity").inner_text())-chosen["capacityMW"]) <= .051
            assert page.locator("#detail-source").get_attribute("href") == chosen["sourceUrl"]
            assert facts(page, "#detail-facts")["Current site output"] == "Unavailable"
            bubble = page.locator(f'.generation-marker[data-site-id="{chosen_id}"] .generation-bubble')
            large_radius = float(bubble.get_attribute("r"))
            large_key = page.locator("#bubble-scale i").evaluate_all("items=>items.map(item=>item.getBoundingClientRect().width)")
            for _ in range(6):
                page.locator("#zoom-out").click()
            small_radius = float(bubble.get_attribute("r"))
            small_key = page.locator("#bubble-scale i").evaluate_all("items=>items.map(item=>item.getBoundingClientRect().width)")
            assert small_radius < large_radius, (small_radius, large_radius)
            assert max(small_key) < max(large_key), (small_key, large_key)
            radius_before_filter = float(bubble.get_attribute("r"))
            camera_before_filter = map_scale(page)
            page.locator("#site-search").fill(chosen_id)
            page.wait_for_function("document.querySelector('#site-count').textContent==='1'")
            assert_mode(page, 'sites')
            assert map_scale(page) == camera_before_filter, 'Typing must not pan or zoom the map'
            assert float(bubble.get_attribute("r")) == radius_before_filter
            page.locator("#clear-site").click()
            assert page.evaluate('document.activeElement.dataset.siteId') == chosen_id
            page.locator("#fit-results").click()
            marker = page.locator(f'.generation-marker[data-site-id="{chosen_id}"]')
            marker.focus()
            marker.press("Enter")
            assert page.locator("#detail-name").inner_text() == chosen["name"]
            assert facts(page, "#detail-facts")["Current site output"] == "Unavailable"
            print("PASS real site source/capacity, unavailable output, marker selection, shrinking bubbles/legend and fixed filter scale")

            page.locator('#reset-filters').click()
            # Compare camera scales in the same layout: Overview has a different legend height.
            page.locator('#sites-view').click()
            page.wait_for_timeout(80)
            national_scale = map_scale(page)
            page.locator('#overview-view').click()
            page.evaluate('''id=>{const input=document.querySelector('#site-search');input.value=id;input.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#fit-results').click();}''', chosen_id)
            assert site_count(page) == 1
            assert_mode(page, 'sites')
            page.wait_for_timeout(80)
            first_fit = map_scale(page)
            assert first_fit >= national_scale*7.9, 'Fit results must flush a search that is still being debounced'
            page.locator('#fit-results').click()
            assert abs(map_scale(page)-first_fit) < .01, 'Repeated Fit results for one site must not keep doubling zoom'
            page.locator('#reset-map').click()
            assert_mode(page, 'overview')
            assert page.locator('#site-search').input_value() == chosen_id
            assert site_count(page) == 1
            page.locator('#site-search').press('Enter')
            assert_mode(page, 'sites')
            assert map_scale(page) >= national_scale*7.9, 'Enter commits and frames the search without automatic panning on every keystroke'
            print('PASS pending-search fit, Enter commit and stable repeated fit for a single site')

            page.locator('#reset-filters').click()
            blank = blank_map_point(page)
            page.locator('#generation-map').evaluate("svg=>svg.addEventListener('pointerdown',event=>window.qaPointerId=event.pointerId,{once:true})")
            page.mouse.move(blank['x'], blank['y'])
            page.mouse.down()
            page.locator('#generation-map').evaluate('svg=>svg.releasePointerCapture(window.qaPointerId)')
            page.mouse.move(0, 0)
            page.mouse.up()
            page.wait_for_timeout(50)
            stopped = page.locator('.generation-land').get_attribute('transform')
            page.mouse.move(blank['x']+30, blank['y']+25)
            page.wait_for_timeout(50)
            assert page.locator('.generation-land').get_attribute('transform') == stopped
            assert page.locator('#generation-map').evaluate('svg=>svg.style.cursor') == 'grab'
            assert page.locator('#site-detail').is_hidden()
            print('PASS lost pointer capture and outside release do not leave a stuck drag or phantom site selection')

            page.locator("#reset-filters").click()
            page.locator("#site-search").fill("not-a-real-site-qa-987654")
            page.wait_for_function("document.querySelector('#site-count').textContent==='0'")
            assert page.locator("#empty-map").is_visible()
            assert page.locator("#export-sites").is_disabled()
            page.locator("#reset-filters").click()
            assert site_count(page) == total

            page.locator("#snapshot-tab").click()
            page.wait_for_function("document.querySelectorAll('#generation-mix .fuel-row').length===10")
            live = facts(page, "#live-totals")
            assert mw(live["Metered output + storage"]) == 800
            assert mw(live["Imports to GB"]) == 1000
            assert mw(live["Exports from GB"]) == 500
            assert mw(live["Net imports"]) == 500
            assert "-50" in page.locator('.fuel-row[data-code="PS"]').inner_text()
            assert "-20" in page.locator('.fuel-row[data-code="OTHER"]').inner_text()
            fail_feed["value"] = True
            page.locator("#refresh-live").click()
            page.wait_for_function("document.querySelector('#live-status').textContent.includes('previous observation')")
            assert facts(page, "#live-totals") == live
            print("PASS coherent national mix/signed transfers and explicit previous-observation retention after failed refresh")

            page.locator("#sites-tab").click()
            for width, height in [(320, 740), (390, 844), (1366, 768), (1440, 900)]:
                page.set_viewport_size({"width": width, "height": height})
                page.wait_for_timeout(80)
                size = page.evaluate("({width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight})")
                assert size["scrollWidth"] <= width+1, size
                if width >= 850:
                    assert size["scrollHeight"] <= height+1, size
                overlaps = page.locator('.generation-region-label:visible').evaluate_all('''labels=>{
                  const collisions=[];
                  labels.forEach((a,index)=>labels.slice(index+1).forEach(b=>{
                    const first=a.getBoundingClientRect(),second=b.getBoundingClientRect();
                    if(first.left<second.right&&first.right>second.left&&first.top<second.bottom&&first.bottom>second.top)collisions.push([a.textContent,b.textContent]);
                  }));
                  return collisions;
                }''')
                assert not overlaps, (width, overlaps)
            assert not errors, errors
            print("PASS 320/390/1366/1440 responsive bounds, readable region labels, empty-search reset and no runtime errors")

            unavailable = context.new_page()
            unavailable.route("**/datasets/FUELINST?*", lambda route: route.abort("failed"))
            unavailable.goto(PAGE_URL)
            ready(unavailable)
            unavailable.locator("#snapshot-tab").click()
            unavailable.wait_for_function("document.querySelector('#open-snapshot').textContent.includes('unavailable')")
            assert all(value == "—" for value in facts(unavailable, "#live-totals").values())
            assert unavailable.locator("#generation-mix .fuel-row").count() == 0
            assert site_count(unavailable) == total
            assert unavailable.locator("#catalogue-error").is_hidden()
            print("PASS initial feed failure leaves real catalogue usable and never substitutes synthetic site/live output")
            browser.close()


if __name__ == "__main__":
    run()
