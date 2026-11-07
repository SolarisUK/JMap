"""Offline browser regression checks. Run with global Python Playwright.

All temporary downloads stay beneath UI/tests; no server or API is required.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
import sys
import tempfile

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
TEST_DIR = Path(__file__).resolve().parent
PAGE_URL = (TEST_DIR.parent / "operations.html").as_uri()


def ready(page):
    page.wait_for_function("!document.querySelector('#export-transfers').disabled", timeout=20000)
    assert page.locator("#error-banner").is_hidden(), page.locator("#error-message").inner_text()


def current(page):
    return page.evaluate("""() => {
      const b=window.JMAP_SIMULATION_STUBS,scenario=document.querySelector('#scenario').value,
        strategy=document.querySelector('#strategy').value,step=+document.querySelector('#time-step').value;
      return {scenario,strategy,step,snapshot:b.states[scenario][strategy][step],edges:b.edges.edges||b.edges};
    }""")


def facts(page, selector):
    return page.locator(selector).evaluate("element=>Object.fromEntries([...element.children].map(row=>[row.querySelector('dt').textContent,row.querySelector('dd').textContent]))")


def mw(text):
    return float(text.replace(",", "").replace(" MW", ""))


def verify_zone_accounting(page, zone):
    assert page.locator("#transfer-zone-detail").is_visible()
    data = current(page)
    incoming = outgoing = 0.0
    for edge in data["edges"]:
        if zone not in (edge["from"], edge["to"]):
            continue
        measured = data["snapshot"]["edges"][edge["edge_id"]]
        if measured.get("limit_mw") == 0:
            continue
        flow = measured["flow_mw"]
        source, target = (edge["to"], edge["from"]) if flow < 0 else (edge["from"], edge["to"])
        if target == zone:
            incoming += abs(flow)
        if source == zone:
            outgoing += abs(flow)
    shown = facts(page, "#transfer-zone-totals")
    assert abs(mw(shown["Incoming"]) - incoming) <= .051, (shown, incoming)
    assert abs(mw(shown["Outgoing"]) - outgoing) <= .051, (shown, outgoing)
    net_label = "Net import" if incoming-outgoing > .05 else "Net export" if incoming-outgoing < -.05 else "Net transfer"
    assert abs(mw(shown[net_label]) - abs(incoming-outgoing)) <= .051, (shown, incoming-outgoing)


def transfer_csv(page):
    with page.expect_download() as event:
        page.locator("#export-transfers").click()
    download = event.value
    text = Path(download.path()).read_text(encoding="utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    header = next(index for index, row in enumerate(rows) if row and row[0] == "Corridor")
    return rows[:header], list(csv.DictReader(io.StringIO("\n".join(",".join('"'+cell.replace('"','""')+'"' for cell in row) for row in rows[header:]))))


def fixture(page, mutation):
    page.add_init_script("""(() => {
      let bundle;
      Object.defineProperty(window,'JMAP_SIMULATION_STUBS',{configurable:true,
        get:()=>bundle,set:value=>{bundle=value;(""" + mutation + """)(bundle);}});
    })();""")


def run():
    with tempfile.TemporaryDirectory(prefix="transfer-qa-", dir=TEST_DIR) as folder:
        download_dir = Path(folder).resolve()
        assert download_dir.is_relative_to(TEST_DIR)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, downloads_path=str(download_dir))
            context = browser.new_context(viewport={"width": 1366, "height": 900}, accept_downloads=True, reduced_motion="no-preference")
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(PAGE_URL)
            ready(page)
            assert "Generated demo" in page.locator("#data-status").inner_text()
            assert page.locator("#panel-transfers").is_visible()
            assert page.locator("#network-transfer-list .transfer-row").count() == len(current(page)["edges"])

            data = current(page)
            negative = next(edge for edge in data["edges"] if data["snapshot"]["edges"][edge["edge_id"]]["flow_mw"] < -.05 and data["snapshot"]["edges"][edge["edge_id"]].get("limit_mw") != 0)
            edge_id = negative["edge_id"]
            route = page.locator(f'#response-map .simulation-edge[data-edge-id="{edge_id}"]')
            route.focus()
            route.press("Enter")
            assert page.locator("#transfer-edge-detail").is_visible()
            assert edge_id in page.locator("#transfer-edge-title").inner_text()
            assert mw(facts(page, "#transfer-edge-facts")["Signed measurement"]) < 0
            page.locator("#zone").select_option(negative["from"])
            verify_zone_accounting(page, negative["from"])
            print("PASS keyboard route selection, reverse flow and selected-zone accounting")

            old_flow = current(page)["snapshot"]["edges"][edge_id]["flow_mw"]
            old_step = current(page)["step"]
            page.locator("#next-frame").click()
            page.wait_for_function("step=>new URL(location.href).searchParams.get('step')===String(step)&&!document.querySelector('#export-transfers').disabled", arg=old_step+1)
            ready(page)
            verify_zone_accounting(page, negative["from"])
            updated = current(page)["snapshot"]["edges"][edge_id]["flow_mw"]
            assert updated != old_flow
            assert str(updated) in page.locator(f'#response-map .simulation-edge[data-edge-id="{edge_id}"]').get_attribute("aria-label")
            metadata, exported = transfer_csv(page)
            row = next(row for row in exported if row["Corridor"] == edge_id)
            assert float(row["Signed MW"]) == updated
            assert row["Flow source"] == negative["to"] and row["Flow destination"] == negative["from"]
            assert any(row == ["Timestamp UTC", current(page)["snapshot"]["timestamp_utc"]] for row in metadata)
            print("PASS next-frame updates panel/map and CSV preserves signed flow/direction")

            page.locator("#open-notes").click()
            page.locator("#show-transfer-values").uncheck()
            assert page.locator("#response-map .simulation-transfer-labels").get_attribute("display") == "none"
            page.locator("#animate-transfers").check()
            assert page.locator('#response-map .simulation-flow-particle[display="inline"]').count() > 0
            page.locator('[data-close="notes-dialog"]').click()
            page.reload()
            ready(page)
            assert not page.locator("#show-transfer-values").is_checked()
            assert page.locator("#animate-transfers").is_checked()
            assert "values=0" in page.url and "motion=1" in page.url
            page.locator("#open-notes").click()
            page.locator("#show-transfer-values").check()
            page.locator('[data-close="notes-dialog"]').click()
            print("PASS MW/motion controls and URL reload persistence")

            page.evaluate("""() => {const original=OperationsApi.prototype.series;
              OperationsApi.prototype.series=async function(...args){await new Promise(resolve=>setTimeout(resolve,350));return original.apply(this,args);};}""")
            page.locator("#scenario").select_option("cold_snap")
            for selector in ["#export-episode", "#export-results", "#export-transfers"]:
                assert page.locator(selector).is_disabled(), selector
            ready(page)
            metadata, _ = transfer_csv(page)
            assert metadata[0] == ["JMap simulated transfers", "cold_snap"]
            print("PASS scenario reload disables exports until accepted data, with correct CSV identity")

            for width in [390, 1366, 1440]:
                page.set_viewport_size({"width": width, "height": 900})
                page.wait_for_timeout(80)
                sizes = page.evaluate("({width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight})")
                assert sizes["scrollWidth"] <= width+1, sizes
                if width >= 850:
                    assert sizes["scrollHeight"] <= sizes["height"]+1, sizes
            assert not errors, errors
            print("PASS 390/1366/1440 layouts and no browser runtime errors")

            unknown = context.new_page()
            fixture(unknown, "bundle=>{for(const strategies of Object.values(bundle.states))for(const frames of Object.values(strategies))for(const frame of frames)delete frame.edges['MIDL-EAST'].flow_mw;}")
            unknown.goto(PAGE_URL+"?zone=MIDL&focus=zone")
            ready(unknown)
            assert unknown.locator("#transfer-zone-detail").is_visible()
            assert all(value == "—" for value in facts(unknown, "#transfer-zone-totals").values())
            assert "unavailable" in unknown.locator("#transfer-zone-note").inner_text()
            missing_row = unknown.locator('#network-transfer-list [data-transfer-edge="MIDL-EAST"]')
            assert missing_row.get_attribute("data-status") == "unknown"
            assert "Flow unavailable" in (missing_row.get_attribute("aria-label") or "")
            assert "—" in missing_row.inner_text()
            _, exported = transfer_csv(unknown)
            missing = next(row for row in exported if row["Corridor"] == "MIDL-EAST")
            assert missing["Signed MW"] == "" and missing["Effective transfer MW"] == ""
            assert missing["Flow source"] == "" and missing["Flow destination"] == ""
            print("PASS missing flow stays unknown in panel and CSV")

            out = context.new_page()
            fixture(out, "bundle=>{for(const strategies of Object.values(bundle.states))for(const frames of Object.values(strategies))for(const frame of frames)Object.assign(frame.edges['SSCO-NORT'],{flow_mw:0,limit_mw:0,loading_frac:0,tripped:true});}")
            out.goto(PAGE_URL)
            ready(out)
            out.locator('#network-transfer-list [data-transfer-edge="SSCO-NORT"]').click()
            assert facts(out, "#transfer-edge-facts")["From / to"] == "Out of service"
            _, exported = transfer_csv(out)
            corridor = next(row for row in exported if row["Corridor"] == "SSCO-NORT")
            assert corridor["Status"] == "out" and corridor["Effective transfer MW"] == "0"
            assert corridor["Flow source"] == "" and corridor["Flow destination"] == ""
            assert out.locator('#response-map .simulation-edge[data-edge-id="SSCO-NORT"]').get_attribute("data-band") == "out"
            print("PASS zero-capacity OUT has no active direction in panel, map or CSV")
            browser.close()


if __name__ == "__main__":
    run()
