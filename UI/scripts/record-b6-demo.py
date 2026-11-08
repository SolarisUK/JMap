"""Record a 150-second, API-backed B6 walkthrough without changing the dashboard.

Run with the standard API already listening on port 8000. Playwright/Chromium are
required. Pass --ffmpeg with an H.264/libass-capable executable to also make MP4.
All incident positions, captions and result figures are read at recording time.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time
from urllib.parse import urlencode
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

UI = Path(__file__).resolve().parents[1]
DURATION = 150


def timestamp(seconds, ass=False):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    if ass:
        return f'{hours}:{minutes:02}:{seconds:02}.{milliseconds // 10:02}'
    return f'{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', default='http://127.0.0.1:8000')
    parser.add_argument('--scenario', default='b6_trip_windy_peak')
    parser.add_argument('--out', type=Path, default=UI / 'recordings')
    parser.add_argument('--ffmpeg', type=Path)
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)

    def get(endpoint, **params):
        with urlopen(args.api.rstrip('/') + endpoint + '?' + urlencode(params), timeout=15) as reply:
            return json.load(reply)

    comparison = get('/compare', scenario=args.scenario)
    runs = {strategy: get('/state/series', scenario=args.scenario, strategy=strategy)['frames']
            for strategy in ('none', 'optimiser')}
    for frames in runs.values():
        for frame in frames:
            for key in ('zones', 'edges'):
                if isinstance(frame[key], dict):
                    frame[key] = [dict(id=name, **value) for name, value in frame[key].items()]
    scenario = next(item for item in get('/scenarios')['scenarios'] if item['name'] == args.scenario)
    boundary = next(item['target'] for item in scenario['incidents'] if item['type'] == 'line_trip')
    first_trip = next(i for i, frame in enumerate(runs['none'])
                      if any(incident['type'] == 'line_trip' and incident['target'] == boundary for incident in frame['incidents']))
    last_intact = max(i for i, frame in enumerate(runs['none'][:first_trip])
                      if any(edge['id'] == boundary and not edge['tripped'] for edge in frame['edges']))
    first_shortage = next(i for i, frame in enumerate(runs['none'])
                          if any(zone['unserved_mw'] >= .05 for zone in frame['zones']))
    active = [i for i, frame in enumerate(runs['none'])
              if any(incident['type'] == 'line_trip' and incident['target'] == boundary for incident in frame['incidents'])
              and any(zone['unserved_mw'] >= .05 for zone in frame['zones'])]
    middle = active[len(active) // 2]
    england_wales = [zone for zone in get('/reference')['zone_order'] if zone not in ('NSCO', 'SSCO')]
    assert len(england_wales) == 8
    trip_frame = runs['none'][first_trip]
    assert all(zone['unserved_mw'] >= .05 for zone in trip_frame['zones'] if zone['id'] in england_wales)
    scottish_curtailed = sum(zone['curtailed_mw'] for zone in trip_frame['zones'] if zone['id'] in ('NSCO', 'SSCO'))
    assert scottish_curtailed > 0, 'Review the captions: no spare Scottish generation is recorded.'
    trip_date = datetime.fromisoformat(trip_frame['timestamp_utc'])
    trip_label = trip_date.strftime('%H:%M UTC on %d %b %Y')
    scotland_unserved = max(zone['unserved_mw'] for frame in runs['none']
                           for zone in frame['zones'] if zone['id'] in ('NSCO', 'SSCO'))
    assert scotland_unserved < .05, 'Review the captions: the Scottish supply story changed.'
    assert max(edge['loading_frac'] for frame in runs['optimiser'] for edge in frame['edges']) <= 1 + 1e-6
    assert max(zone['unserved_mw'] for frame in runs['optimiser'] for zone in frame['zones']) < .05
    errors, scenes = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={'width': 1600, 'height': 840},
                                      record_video_dir=str(args.out / 'raw'),
                                      record_video_size={'width': 1600, 'height': 840},
                                      reduced_motion='no-preference')
        page_created = time.monotonic()
        page = context.new_page()
        video = page.video
        page.on('pageerror', lambda error: errors.append(str(error)))
        cdp = context.new_cdp_session(page)
        cdp.send('Network.enable')
        cdp.send('Network.setCacheDisabled', {'cacheDisabled': True})
        page.goto((UI / 'operations.html').as_uri() + '?' + urlencode({
            'api': args.api, 'scenario': args.scenario, 'step': 0, 'motion': 1}))
        cdp.send('Page.reload', {'ignoreCache': True})

        def ready():
            page.wait_for_function("!document.querySelector('#export-transfers').disabled || !document.querySelector('#error-banner').hidden")
            assert page.locator('#error-banner').is_hidden(), page.locator('#error-message').inner_text()

        ready()
        page.mouse.move(1590, 830)
        start = time.monotonic()
        pre_roll = start - page_created

        def at(seconds):
            remaining = start + seconds - time.monotonic()
            if remaining > 0:
                page.wait_for_timeout(remaining * 1000)

        def mark(name):
            scenes.append({'second': round(time.monotonic() - start, 2), 'scene': name,
                           'frame': int(page.locator('#time-step').input_value()),
                           'timestamp': page.locator('#frame-time').inner_text()})
            print(json.dumps(scenes[-1], ensure_ascii=True), flush=True)

        def seek(step):
            page.locator('#time-step').evaluate("(e,value)=>{e.value=value;e.dispatchEvent(new Event('input',{bubbles:true}));}", step)
            ready()
            page.wait_for_function('(n)=>document.querySelector("#frame-count").textContent.trim().startsWith(`${n+1} /`)', arg=step)
            assert page.locator('#response-map .simulation-edge[data-band="overload"]').count() == 0

        mark('Demand served before the outage')
        at(20)
        # Use the real playback control, then stop just before the first tripped frame.
        page.locator('#play').click()
        page.mouse.move(1590, 830)
        page.wait_for_function('(n)=>Number(document.querySelector("#time-step").value)>=n', arg=last_intact, timeout=60000)
        if page.locator('#play').get_attribute('aria-pressed') == 'true':
            page.locator('#play').click()
        seek(last_intact)
        mark('Playback paused before the B6 trip')
        at(52)
        route = page.locator(f'#response-map .simulation-edge[data-edge-id="{boundary}"]')
        route.focus()
        route.press('Enter')
        page.mouse.move(1590, 830)
        mark('Inspect the B6 boundary')
        at(64)
        seek(first_trip)
        mark('B6 trips at the recorded incident time in both runs')
        at(72)
        seek(first_shortage)
        page.locator('#clear-map-selection').click()
        zone = page.locator('#response-map .simulation-zone-label[data-zone-id="NSCO"]')
        zone.focus()
        zone.press('Enter')
        page.locator('[data-tab="inspect"]').click()
        page.mouse.move(1590, 830)
        mark('Scotland islanded with surplus wind, still supplied')
        at(86)
        page.locator('#clear-map-selection').click()
        page.locator('[data-tab="transfers"]').click()
        page.mouse.move(1590, 830)
        page.wait_for_timeout(200)
        mark('All eight England and Wales zones go short on the no-response side')
        page.screenshot(path=str(args.out / 'b6-split-screen.png'))
        at(108)
        seek(middle)
        page.mouse.move(1590, 830)
        mark('Hold the active incident')
        at(120)
        page.locator('[data-tab="results"]').click()
        page.mouse.move(1590, 830)
        mark('Full-episode scoreboard')
        headline = page.locator('#result-headline').inner_text()
        scoreboard = page.locator('#results-table').inner_text()
        page.screenshot(path=str(args.out / 'b6-scoreboard.png'))
        at(DURATION + 1)
        assert not errors, errors
        context.close()
        video.save_as(str(args.out / 'b6-demo-source.webm'))
        video.delete()
        browser.close()

    totals = comparison['strategies']
    baseline, optimiser = totals['none'], totals['optimiser']
    number = lambda value: f'{value:,.0f}'
    money = lambda value: f'\u00a3{value / 1e6:,.1f}M'
    captions = [
        (0, 12, 'Same B6 contingency. Left: no response. Right: linear-programming optimiser.'),
        (12, 20, 'Before the outage: demand is served in both runs. Line colours show corridor loading.'),
        (20, 40, 'Half-hour snapshots advance together. Arrowheads show the direction of electricity flow.'),
        (40, 52, 'Surplus Scottish wind is exported over B6 towards England.'),
        (52, 64, f'Inspecting {boundary}: flow and capacity come from the API.'),
        (64, 72, f'B6 trips at {trip_label}. Scotland is cut off from England.'),
        (72, 86, 'Scotland is islanded WITH SURPLUS wind and stays supplied. Curtailment shows spare generation.'),
        (86, 104, 'No response: all eight England and Wales zones, NORT through SOUT, develop shortfalls.'),
        (104, 108, 'The optimiser keeps demand served, with no red overloaded lines throughout the episode.'),
        (108, 120, f'{headline} at dashboard precision across the full episode.'),
        (120, 132, f"Full episode: {number(baseline['unserved_mwh'])} vs {number(optimiser['unserved_mwh'])} MWh unserved. Costs: {money(baseline['cost_gbp'])} vs {money(optimiser['cost_gbp'])}."),
        (132, 140, f"Optimiser model penalty: {money(optimiser['penalty_gbp'])}. Model penalties remain separate from cost."),
        (140, DURATION, 'RL policies were also trained; they did not beat the optimiser.'),
    ]
    srt = '\n\n'.join(f'{i}\n{timestamp(begin)} --> {timestamp(end)}\n{text}'
                      for i, (begin, end, text) in enumerate(captions, 1)) + '\n'
    (args.out / 'b6-demo.srt').write_text(srt, encoding='utf-8')
    ass = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1600
PlayResY: 900
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Segoe UI,22,&H00EEEEEE,&H00EEEEEE,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,30,30,17,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    ass += '\n'.join(f'Dialogue: 0,{timestamp(begin, True)},{timestamp(end, True)},Default,,0,0,0,,{text}'
                     for begin, end, text in captions) + '\n'
    (args.out / 'b6-demo.ass').write_text(ass, encoding='utf-8-sig')
    manifest = {'duration_seconds': DURATION, 'source_pre_roll_seconds': pre_roll,
                'api': args.api, 'scenario': args.scenario, 'comparison': comparison,
                'scene_timeline': scenes, 'scoreboard_text': scoreboard, 'headline': headline,
                'first_trip_timestamp_utc': runs['none'][first_trip]['timestamp_utc'],
                'first_shortage_timestamp_utc': runs['none'][first_shortage]['timestamp_utc'],
                'england_wales_shortage_zones': england_wales,
                'scottish_curtailed_mw_at_trip': scottish_curtailed,
                'api_py_sha256': hashlib.sha256((UI.parent / 'api.py').read_bytes()).hexdigest(),
                'captions': [{'start': a, 'end': b, 'text': c} for a, b, c in captions]}
    (args.out / 'b6-demo.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')
    guide = f'''# B6 backup recording

The captioned MP4 is a 2 minute 30 second recording of the local dashboard using the running API. It has no audio; the subtitles provide a timed voiceover script. Keep a local copy on the demo laptop and test playback before presenting.

Start the API with `uvicorn api:app --port 8000`. The recording disables browser caching and hard-refreshes the dashboard. It uses the actual timeline, route inspection and Results controls; it does not alter figures, map colours or API responses.

## Run of show

''' + '\n'.join(f'- {timestamp(a)[:8]}: {c}' for a, _, c in captions) + f'''

## Data notes

- Scotland is islanded WITH SURPLUS wind and stays supplied. All eight England and Wales zones (NORT, YORK, WALE, MIDL, EAST, SWES, LOND, SOUT) develop shortfalls in the no-response run. The optimiser has zero displayed unserved MWh and no overloaded lines throughout the episode.
- The optimiser's raw full-episode residual is {optimiser['unserved_mwh']!r} MWh; the dashboard correctly rounds it to zero at its display precision. Its raw penalty is GBP {optimiser['penalty_gbp']!r}, shown separately from cost.
- The recorded B6 incident starts at {runs['none'][first_trip]['timestamp_utc']}; shortfalls begin at {runs['none'][first_shortage]['timestamp_utc']}. The recording uses the active incident's timestamp, rather than next-decision availability, to label the trip.
- Every cost and penalty is shown in GBP millions with one decimal. The supplied raw penalty remains unchanged; its displayed value is {money(optimiser['penalty_gbp'])}.
- `b6-demo.json` captures the runtime comparison and scene timings. The source WebM has the untrimmed initial page load; the MP4 removes only that setup and preserves the full 150-second walkthrough.

## Refresh for new data

Run the existing exporter: `python -B UI/scripts/export-api-stubs.py --backend-root dhruv_latest`, restart the API, then rerun `python -B UI/scripts/record-b6-demo.py --ffmpeg PATH_TO_FFMPEG`. Captions and figures regenerate from the running API. The script stops for review if the Scottish supply story or optimiser overload/shortage guarantees change.

Rehearse twice on the presentation laptop with a timer. On each run check the boundary trip, left/right contrast, zero-unserved headline, final scoreboard, and offline MP4 playback. This capture does not verify that physical laptop or projector.
'''
    (args.out / 'README.md').write_text(guide, encoding='utf-8')
    if args.ffmpeg:
        subprocess.run([str(args.ffmpeg.resolve()), '-hide_banner', '-loglevel', 'warning', '-y', '-ss', str(pre_roll),
                        '-i', 'b6-demo-source.webm', '-t', str(DURATION),
                        '-vf', 'pad=1600:900:0:0:color=black,ass=b6-demo.ass,scale=1920:1080',
                        '-c:v', 'libx264', '-preset', 'fast', '-crf', '19', '-pix_fmt', 'yuv420p',
                        '-movflags', '+faststart', '-an', 'b6-demo.mp4'], cwd=args.out, check=True)
    print(f'Recording complete: {args.out}', flush=True)


if __name__ == '__main__':
    main()
