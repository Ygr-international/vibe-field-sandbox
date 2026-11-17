# -*- coding: utf-8 -*-
"""电场沙盘 Playwright 自检：python tests/test_sandbox.py（需 playwright + Chromium）"""
import math, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
URL = (ROOT / "index.html").as_uri()
SHOTS = ROOT / "shots"
SHOTS.mkdir(exist_ok=True)
FAILS = []

def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        FAILS.append(name)

def attach(page):
    errs, reqs = [], []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    page.on("request", lambda r: reqs.append(r.url))
    return errs, reqs

def wait_api(page):
    page.wait_for_function("window.__sandbox && window.__sandbox.getState().w > 0")

def st(page):
    return page.evaluate("window.__sandbox.getState()")

def drag_mouse(page, x1, y1, x2, y2, steps=6):
    page.mouse.move(x1, y1)
    page.mouse.down()
    for i in range(1, steps + 1):
        page.mouse.move(x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps)
    page.mouse.up()

def desktop(pw):
    br = pw.chromium.launch()
    pg = br.new_page(viewport={"width": 1920, "height": 1080})
    errs, reqs = attach(pg)
    pg.goto(URL)
    wait_api(pg)
    pg.wait_for_timeout(400)
    check("desktop: zero console/page errors", errs == [], str(errs[:3]))
    check("desktop: exactly 1 request (zero deps)", len(reqs) == 1, str(reqs))
    s = st(pg)
    check("desktop: free mode, 2 charges", s["mode"] == "free" and len(s["charges"]) == 2)
    check("desktop: dipole readout 2.00", abs(s["ratio"] - 2.0) < 1e-6, f"ratio={s['ratio']}")
    pg.screenshot(path=str(SHOTS / "shot-desktop-free.png"))
    # real mouse drag
    p0 = pg.evaluate("window.__sandbox.chargeScreenPos(0)")
    r0 = pg.evaluate("window.__sandbox.getRatio()")
    drag_mouse(pg, p0["cx"], p0["cy"], p0["cx"] + 120, p0["cy"] - 80)
    s2 = st(pg)
    check("desktop: drag moved charge", abs(s2["charges"][0]["x"] - s["charges"][0]["x"]) > 0.01)
    check("desktop: drag changed ratio", abs(pg.evaluate("window.__sandbox.getRatio()") - r0) > 1e-3)
    check("desktop: moves counter +1", s2["moves"] == s["moves"] + 1, f"{s['moves']}→{s2['moves']}")
    # keyboard
    pg.evaluate("window.__sandbox.select(0)")
    x_before = st(pg)["charges"][0]["x"]
    for _ in range(5):
        pg.keyboard.press("ArrowRight")
    check("desktop: keyboard nudge", st(pg)["charges"][0]["x"] > x_before)
    pg.keyboard.press("Escape")
    check("desktop: Escape deselect", st(pg)["selected"] == -1)
    pg.evaluate("window.__sandbox.addCharge('+',1,0.5,0.2)")
    n = len(st(pg)["charges"])
    pg.evaluate("window.__sandbox.select(2)")
    pg.keyboard.press("Delete")
    check("desktop: Delete removes", len(st(pg)["charges"]) == n - 1)
    # flowing field lines: cached when idle, recomputed after drag
    fl1 = pg.evaluate("window.__sandbox.fieldLineStats()")
    check("fieldlines: present for dipole", fl1["count"] >= 6, str(fl1["count"]))
    pg.wait_for_timeout(300)
    fl2 = pg.evaluate("window.__sandbox.fieldLineStats()")
    check("fieldlines: cached when idle (no rebuild)", fl2["build"] == fl1["build"], f'{fl1["build"]}→{fl2["build"]}')
    p0 = pg.evaluate("window.__sandbox.chargeScreenPos(0)")
    drag_mouse(pg, p0["cx"], p0["cy"], p0["cx"] - 70, p0["cy"] + 50)
    fl3 = pg.evaluate("window.__sandbox.fieldLineStats()")
    check("fieldlines: recomputed after drag", fl3["build"] > fl1["build"] and fl3["hash"] != fl1["hash"],
          f'build {fl1["build"]}→{fl3["build"]}')
    # fire electron via real button + canvas tap (negative test charge, against E)
    ratio_before = pg.evaluate("window.__sandbox.getRatio()")
    charges_before = st(pg)["charges"]
    pg.click("#btnElectron")
    check("electron: button arms", pg.get_attribute("#btnElectron", "aria-pressed") == "true")
    rect = pg.evaluate("(()=>{const r=document.getElementById('c').getBoundingClientRect();return{l:r.left,t:r.top,w:r.width,h:r.height}})()")
    pg.mouse.click(rect["l"] + 0.5 * rect["w"], rect["t"] + 0.28 * rect["h"])
    pg.wait_for_timeout(150)
    els = pg.evaluate("window.__sandbox.getElectrons()")
    check("electron: spawned on tap", len(els) >= 1, str(len(els)))
    if els:
        e = els[0]
        dot = e["vx"] * e["ex"] + e["vy"] * e["ey"]
        check("electron: moves against E (v·E<0)", dot < 0, f"v·E={dot:.3f}")
    check("electron: disarms after fire", pg.get_attribute("#btnElectron", "aria-pressed") == "false")
    check("electron: does not disturb charges", st(pg)["charges"] == charges_before)
    check("electron: does not source field (ratio unchanged)",
          abs(pg.evaluate("window.__sandbox.getRatio()") - ratio_before) < 1e-9)
    gone = False
    for _ in range(50):
        pg.wait_for_timeout(100)
        if pg.evaluate("window.__sandbox.electronCount()") == 0:
            gone = True; break
    check("electron: disappears on hit/bounds", gone)
    # challenge basic win via API
    pg.evaluate("window.__sandbox.setMode('challenge')")
    pg.evaluate("window.__sandbox.reset()")
    check("challenge: initial ratio > 0.02", pg.evaluate("window.__sandbox.getRatio()") > 0.02)
    pg.evaluate("window.__sandbox.setCharge(0,0.35,0.5);window.__sandbox.setCharge(1,0.65,0.5)")
    check("challenge: mirror pair ratio ~0", pg.evaluate("window.__sandbox.getRatio()") < 1e-9)
    pg.wait_for_timeout(500)
    check("challenge: winProgress climbs", pg.evaluate("window.__sandbox.winProgress()") > 0.3)
    pg.wait_for_timeout(1000)
    check("challenge: win latched after hold", pg.evaluate("window.__sandbox.isWin()"))
    pg.wait_for_timeout(600)
    pg.screenshot(path=str(SHOTS / "shot-challenge-win.png"))
    # hysteresis negative
    pg.evaluate("window.__sandbox.reset()")
    s = st(pg)
    dn = s["d0"] / s["w"]
    pg.evaluate(f"window.__sandbox.setCharge(0,0.5-{dn},0.5);window.__sandbox.setCharge(1,0.5+{dn}+0.0125*{dn},0.5)")
    r = pg.evaluate("window.__sandbox.getRatio()")
    check("hysteresis: band ratio ~0.025", 0.02 < r < 0.03, f"r={r:.4f}")
    pg.wait_for_timeout(1500)
    check("hysteresis: no win in band", not pg.evaluate("window.__sandbox.isWin()"))
    pg.evaluate(f"window.__sandbox.setCharge(1,0.5+{dn}+0.005*{dn},0.5)")
    pg.wait_for_timeout(500)
    acc = pg.evaluate("window.__sandbox.winProgress()")
    pg.evaluate(f"window.__sandbox.setCharge(1,0.5+{dn}+0.02*{dn},0.5)")  # ratio~0.04 ≥ EXIT → 清零
    pg.wait_for_timeout(100)
    check("hysteresis: exit resets accum", acc > 0.3 and pg.evaluate("window.__sandbox.winProgress()") == 0)
    pg.wait_for_timeout(1400)
    check("hysteresis: still no win", not pg.evaluate("window.__sandbox.isWin()"))
    # advanced win
    pg.evaluate("window.__sandbox.reset()")
    pg.evaluate("window.__sandbox.setAdvanced(true)")
    s = st(pg)
    dn = s["d0"] / s["w"]
    pg.evaluate(f"window.__sandbox.setCharge(0,0.5-0.8*{dn},0.5);window.__sandbox.setCharge(1,0.5+Math.SQRT2*0.8*{dn},0.5)")
    check("advanced: ratio ~0", pg.evaluate("window.__sandbox.getRatio()") < 1e-9)
    pg.wait_for_timeout(1500)
    check("advanced: win", pg.evaluate("window.__sandbox.isWin()"))
    wt = pg.text_content("#winText")
    check("advanced: reveal mentions √2", "√2" in wt, wt[:40])
    # snap via real drag
    pg.evaluate("window.__sandbox.setAdvanced(false)")
    pg.evaluate("window.__sandbox.reset()")
    pg.evaluate("window.__sandbox.setCharge(0,0.35,0.5)")
    s = st(pg)
    p1 = pg.evaluate("window.__sandbox.chargeScreenPos(1)")
    rect = pg.evaluate("(()=>{const r=document.getElementById('c').getBoundingClientRect();return{l:r.left,t:r.top}})()")
    mx = rect["l"] + 0.65 * s["w"] - 8
    my = rect["t"] + 0.5 * s["h"]
    drag_mouse(pg, p1["cx"], p1["cy"], mx, my, steps=8)
    c1 = st(pg)["charges"][1]
    check("snap: pinned to exact mirror", abs(c1["x"] - 0.65) < 1e-6 and abs(c1["y"] - 0.5) < 1e-6, f"{c1}")
    pg.wait_for_timeout(1500)
    check("snap: win after hold", pg.evaluate("window.__sandbox.isWin()"))
    # screenshot button (desktop → download)
    pg.evaluate("window.__sandbox.setMode('free')")
    with pg.expect_download() as dl:
        pg.click("#btnShot")
    check("screenshot: desktop download", dl.value.suggested_filename == "field-sandbox.png")
    # localStorage persistence —— file:// 是 opaque origin（blob:null），localStorage 不可用；
    # 真实部署在 https Pages 上可用，故此断言走本地 HTTP 服务器。
    import http.server, threading, functools
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
            functools.partial(Quiet, directory=str(ROOT)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    pg2 = br.new_page(viewport={"width": 1920, "height": 1080})
    errs2, _ = attach(pg2)
    pg2.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html")
    wait_api(pg2)
    pg2.wait_for_timeout(300)
    check("persistence(http): boot clean", errs2 == [], str(errs2[:3]))
    pg2.evaluate("window.__sandbox.reset()")
    p0 = pg2.evaluate("window.__sandbox.chargeScreenPos(0)")
    drag_mouse(pg2, p0["cx"], p0["cy"], p0["cx"] + 90, p0["cy"] + 60)
    saved = st(pg2)["charges"][0]
    pg2.reload()
    wait_api(pg2)
    pg2.wait_for_timeout(300)
    restored = st(pg2)["charges"][0]
    check("persistence: layout restored", abs(restored["x"] - saved["x"]) < 1e-6 and abs(restored["y"] - saved["y"]) < 1e-6)
    pg2.close()
    srv.shutdown()
    # file:// 下 localStorage 不可用也不能崩（try/catch 兜底）
    check("persistence(file://): boot survives blocked storage", errs == [], str(errs[:3]))
    # resize during drag
    p0 = pg.evaluate("window.__sandbox.chargeScreenPos(0)")
    pg.mouse.move(p0["cx"], p0["cy"])
    pg.mouse.down()
    pg.mouse.move(p0["cx"] + 40, p0["cy"] + 20)
    pg.set_viewport_size({"width": 1280, "height": 800})
    pg.wait_for_timeout(200)
    pg.mouse.move(700, 400)
    pg.mouse.up()
    pg.wait_for_timeout(200)
    check("resize mid-drag: no errors", errs == [], str(errs[:3]))
    check("resize mid-drag: charge in bounds", all(0.03 <= c["x"] <= 0.97 and 0.03 <= c["y"] <= 0.97 for c in st(pg)["charges"]))
    check("desktop final: errors []", errs == [], str(errs[:3]))
    br.close()

def mobile(pw):
    br = pw.chromium.launch()
    ctx = br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3,
                         is_mobile=True, has_touch=True)
    pg = ctx.new_page()
    errs, reqs = attach(pg)
    pg.goto(URL)
    wait_api(pg)
    pg.wait_for_timeout(400)
    check("mobile: errors []", errs == [], str(errs[:3]))
    check("mobile: dipole 2.00", abs(st(pg)["ratio"] - 2.0) < 1e-6)
    # tap select
    p0 = pg.evaluate("window.__sandbox.chargeScreenPos(0)")
    pg.touchscreen.tap(p0["cx"], p0["cy"])
    check("mobile: tap selects", st(pg)["selected"] == 0)
    # touch drag via CDP
    cdp = ctx.new_cdp_session(pg)
    x1, y1 = p0["cx"], p0["cy"]
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x1, "y": y1}]})
    for i in range(1, 6):
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove",
                 "touchPoints": [{"x": x1 + 15 * i, "y": y1 - 10 * i}]})
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    pg.wait_for_timeout(200)
    check("mobile: touch drag moved charge", st(pg)["charges"][0]["x"] > 0.3)
    # button sizes
    boxes = pg.evaluate("""Array.from(document.querySelectorAll('button'))
        .filter(b=>b.offsetParent!==null)
        .map(b=>{const r=b.getBoundingClientRect();return{w:r.width,h:r.height,id:b.id}})""")
    check("mobile: all buttons >=44px", all(b["w"] >= 44 and b["h"] >= 44 for b in boxes),
          str([b for b in boxes if b["w"] < 44 or b["h"] < 44]))
    pg.screenshot(path=str(SHOTS / "shot-mobile-portrait.png"))
    # rotate
    r_before = pg.evaluate("window.__sandbox.getRatio()")
    pg.set_viewport_size({"width": 844, "height": 390})
    pg.wait_for_timeout(400)
    s = st(pg)
    check("rotate: ratio invariant", abs(pg.evaluate("window.__sandbox.getRatio()") - r_before) < 1e-6,
          f"{r_before}→{pg.evaluate('window.__sandbox.getRatio()')}")
    check("rotate: charges in viewport", all(0.03 <= c["x"] <= 0.97 and 0.03 <= c["y"] <= 0.97 for c in s["charges"]))
    pg.screenshot(path=str(SHOTS / "shot-mobile-landscape.png"))
    # challenge winnable on phone via snap (touch drag to mirror)
    pg.evaluate("window.__sandbox.setMode('challenge');window.__sandbox.reset();window.__sandbox.setCharge(0,0.35,0.5)")
    s = st(pg)
    p1 = pg.evaluate("window.__sandbox.chargeScreenPos(1)")
    rect = pg.evaluate("(()=>{const r=document.getElementById('c').getBoundingClientRect();return{l:r.left,t:r.top}})()")
    mx, my = rect["l"] + 0.65 * s["w"] - 6, rect["t"] + 0.5 * s["h"]
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": p1["cx"], "y": p1["cy"]}]})
    for i in range(1, 7):
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove",
                 "touchPoints": [{"x": p1["cx"] + (mx - p1["cx"]) * i / 6, "y": p1["cy"] + (my - p1["cy"]) * i / 6}]})
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    c1 = st(pg)["charges"][1]
    check("mobile snap: exact mirror", abs(c1["x"] - 0.65) < 1e-6 and abs(c1["y"] - 0.5) < 1e-6, f"{c1}")
    pg.wait_for_timeout(1500)
    check("mobile: challenge winnable", pg.evaluate("window.__sandbox.isWin()"))
    # screenshot overlay (touch → long-press save)
    pg.evaluate("window.__sandbox.setMode('free')")
    pg.click("#btnShot")
    pg.wait_for_timeout(400)
    vis = pg.evaluate("!document.getElementById('shotOverlay').hidden")
    src = pg.evaluate("document.getElementById('shotImg').src")
    check("mobile: long-press overlay with blob img", vis and src.startswith("blob:"), src[:30])
    pg.click("#shotClose")
    # perf smoke: 4x CPU throttle, continuous drag 2s
    pg.evaluate("window.__sandbox.reset()")
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
    pg.evaluate("window.__rafCount=0;(function tick(){window.__rafCount++;requestAnimationFrame(tick)})()")
    p0 = pg.evaluate("window.__sandbox.chargeScreenPos(0)")
    pg.mouse.move(p0["cx"], p0["cy"])
    pg.mouse.down()
    t0 = time.time()
    i = 0
    while time.time() - t0 < 2.0:
        i += 1
        pg.mouse.move(p0["cx"] + 60 * math.cos(i * .3), p0["cy"] + 60 * math.sin(i * .3))
        if i % 20 == 0:  # 场线随拖拽重算的同时保持电子动画负载
            pg.evaluate("window.__sandbox.fireElectron(0.5,0.3)")
    pg.mouse.up()
    fps = pg.evaluate("window.__rafCount") / (time.time() - t0)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
    check("perf: >=30fps under 4x throttle (fieldlines+electrons)", fps >= 30, f"{fps:.1f}fps")
    check("mobile final: errors []", errs == [], str(errs[:3]))
    br.close()

if __name__ == "__main__":
    with sync_playwright() as pw:
        desktop(pw)
        mobile(pw)
    print("\n%d FAILURES" % len(FAILS) if FAILS else "\nALL PASS")
    sys.exit(1 if FAILS else 0)