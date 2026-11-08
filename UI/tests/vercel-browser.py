"""Smoke-check built CDN files plus same-origin calls to the local root API.

Requires the unchanged API on port 8000. Static requests are fulfilled from the
build output; API requests use that running server. No cloud deployment occurs.
"""
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT/'public'
ORIGIN = 'https://jmap-vercel.test'


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width':1440,'height':900})
        errors, api_requests = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def serve(route):
            if not route.request.url.startswith(ORIGIN+'/'):
                # This checks deployment wiring, not the third-party live feed.
                return route.abort()
            parts = urlsplit(route.request.url)
            target = PUBLIC/('index.html' if parts.path == '/' else unquote(parts.path).lstrip('/'))
            if target.resolve().is_relative_to(PUBLIC) and target.is_file():
                mime = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
                return route.fulfill(status=200, content_type=mime, body=target.read_bytes())
            if parts.path in ('/state','/state/series','/compare','/reference'):
                api_requests.append(route.request.url)
            query = '?'+parts.query if parts.query else ''
            reply = route.fetch(url='http://127.0.0.1:8000'+parts.path+query)
            route.fulfill(response=reply)

        page.route('**/*', serve)
        page.goto(ORIGIN+'/?scope=keep#map', wait_until='commit')
        page.wait_for_url(ORIGIN+'/generation.html?scope=keep#map', wait_until='domcontentloaded')
        page.wait_for_function("document.querySelectorAll('.generation-region').length>0")
        page.goto(ORIGIN+'/operations.html?scenario=b6_trip_windy_peak', wait_until='domcontentloaded')
        page.wait_for_function("!document.querySelector('#export-transfers').disabled || !document.querySelector('#error-banner').hidden")
        assert page.locator('#error-banner').is_hidden(), page.locator('#error-message').inner_text()
        assert page.locator('#result-headline').inner_text() == '0 MWh unserved'
        assert api_requests and all(url.startswith(ORIGIN+'/') for url in api_requests)
        assert page.evaluate('window.JMAP_SIMULATION_STUBS === undefined')
        page.goto(ORIGIN+'/explorer.html', wait_until='domcontentloaded')
        page.wait_for_function("document.querySelectorAll('.map-region').length>300")
        page.locator('[data-ranking-nation="S12000017"]').click()
        assert page.locator('.map-region[data-region-key="S12000017"]').get_attribute('aria-pressed') == 'true'
        assert not errors, errors
        browser.close()
    print('PASS built homepage, relative assets, navigation, same-origin API split screen and Highland selection.')


if __name__ == '__main__':
    main()
