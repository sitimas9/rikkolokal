#!/usr/bin/env python3
"""
apmix.ai farm — $2M-token free account (residential IP edition).

Flow:
  1. Chrome real buka https://apmix.ai/login
  2. Force-render Cloudflare Turnstile (sitekey apmix) -> auto-solve di IP rumah
  3. Call Next.js Server Action sendMagicLink(email, token)
  4. Polling magic link dari email temp (mail.tm)
  5. Follow magic link -> session cookie -> ambil API key
  6. Simpan ke apmix_accounts.jsonl

Setup:
  pip install playwright requests
  python apmix_farm.py
  python apmix_farm.py --loop 5

Wajib: WiFi rumah, VPN OFF. IP datacenter -> Turnstile silent-refuse.
"""
import argparse, json, random, re, time, uuid
from datetime import datetime
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

SITEKEY = "0x4AAAAAAEhurpkOqzMwZtC4"
ACTION_SEND_MAGIC = "606ac1c68c2e3141908bfcaaaf0d3dd0f398fea2ad"
BASE = "https://apmix.ai"
OUT = Path(__file__).parent / "apmix_accounts.jsonl"

def log(m):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

def tm_create():
    doms = requests.get("https://api.mail.tm/domains", timeout=20).json()["hydra:member"]
    dom = random.choice(doms)["domain"]
    email = f"apx{random.randint(10**7, 10**8 - 1)}@{dom}"
    pw = "Ax" + uuid.uuid4().hex[:8] + "!9"
    r = requests.post("https://api.mail.tm/accounts", json={"address": email, "password": pw}, timeout=20)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"tm create {r.status_code}: {r.text[:120]}")
    tok = requests.post("https://api.mail.tm/token",
                        json={"address": email, "password": pw}, timeout=20).json()["token"]
    return email, tok

def tm_magic_link(mtok, timeout=180):
    t0 = time.time()
    seen = set()
    while time.time() - t0 < timeout:
        try:
            msgs = requests.get("https://api.mail.tm/messages?page=1",
                                headers={"Authorization": f"Bearer {mtok}"}, timeout=20).json()["hydra:member"]
            for m in msgs:
                if m["id"] in seen:
                    continue
                seen.add(m["id"])
                full = requests.get(f"https://api.mail.tm/messages/{m['id']}",
                                   headers={"Authorization": f"Bearer {mtok}"}, timeout=20).json()
                body = (full.get("text") or "") + " " + (full.get("html") or "") + " " + (full.get("intro") or "")
                links = re.findall(r'https?://apmix\.ai/[^\s"\'<>]+', body)
                for link in links:
                    if "login" in link or "verify" in link or "token" in link or "magic" in link:
                        log(f"    magic link: {link[:80]}...")
                        return link
                # fallback: link pertama yang bukan social/asset
                other = re.findall(r'(https://apmix\.ai/[a-z-]+[^\s"\'<>]*)', body)
                if other and not any("apimix.ai" in o for o in other):
                    return other[0]
        except Exception as e:
            log(f"    tm poll: {str(e)[:60]}")
        time.sleep(5)
    return None

RENDER = """
async (sitekey) => {
  if (!window.turnstile) {
    await new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
      s.async = true; s.onload = resolve; s.onerror = () => reject(new Error('api.js fail'));
      document.head.appendChild(s);
    });
    for (let i = 0; i < 100 && !window.turnstile; i++) await new Promise(r => setTimeout(r, 100));
  }
  if (!window.turnstile) return {ok:false, stage:'no-api'};
  let box = document.getElementById('apx-tsb');
  if (!box) { box = document.createElement('div'); box.id='apx-tsb'; document.body.prepend(box); }
  else box.innerHTML = '';
  window.__apx_t = ''; window.__apx_e = '';
  try {
    const wid = window.turnstile.render(box, {sitekey,
      callback: t => { window.__apx_t = t; },
      'error-callback': e => { window.__apx_e = String(e); }});
    return {ok:true, widgetId:String(wid)};
  } catch(e) { return {ok:false, stage:'rerr:'+e.message}; }
}
"""

def mint_token(page, tries=3):
    for att in range(tries):
        res = page.evaluate(RENDER, SITEKEY)
        if not res.get("ok"):
            log(f"  render fail: {res}")
            time.sleep(3)
            continue
        for i in range(45):
            t = page.evaluate("() => window.__apx_t || ''")
            e = page.evaluate("() => window.__apx_e || ''")
            if len(t) > 50:
                log(f"  token OK ({len(t)} chars, {i+1}s)")
                return t
            if e:
                log(f"  ts error: {e}")
                break
            time.sleep(1)
        log("  reset widget, retry...")
    return None

def launch_browser(p):
    ctx = None
    for channel in ("chrome", "msedge", None):
        try:
            kw = {"headless": False, "args": ["--window-size=1100,800"]}
            if channel:
                kw["channel"] = channel
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(Path(__file__).parent / ".apmix-profile"),
                viewport={"width": 1100, "height": 800},
                **kw,
            )
            log(f"browser: {channel or 'chromium'} OK")
            return ctx
        except Exception as e:
            log(f"browser {channel}: {str(e)[:60]}")
    raise RuntimeError("gak ada browser yang bisa dibuka")

def find_key(page):
    """Cari API key apx_live_ di dashboard/session."""
    patterns = [
        "apx_live_[A-Za-z0-9]{20,}",
        "apx_[a-z]+_[A-Za-z0-9]{20,}",
    ]
    # 1) coba API dengan session cookie
    try:
        for ep in ("/v1/keys", "/v1/api-keys", "/v1/account", "/api/user", "/api/keys"):
            r = page.request.get(BASE + ep)
            txt = r.text
            for pat in patterns:
                m = re.findall(pat, txt)
                if m:
                    return m[0]
    except Exception:
        pass
    # 2) scrape HTML dashboard
    for url in ("/", "/dashboard", "/settings", "/api-keys", "/account"):
        try:
            page.goto(BASE + url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)
            html = page.content()
            for pat in patterns:
                m = re.findall(pat, html)
                if m:
                    return m[0]
        except Exception:
            continue
    return None

def one_account(aff=""):
    email, mtok = tm_create()
    log(f"[1] email temp: {email}")

    with sync_playwright() as p:
        ctx = launch_browser(p)
        page = ctx.new_page()
        try:
            log("[2] buka apmix.ai/login")
            page.goto(BASE + "/login", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)

            log("[3] mint Turnstile token")
            tok = mint_token(page)
            if not tok:
                return None

            log("[4] sendMagicLink (server action)")
            r = page.evaluate("""async ([email, action, token]) => {
                const body = JSON.stringify(email) + '\\n' + JSON.stringify(token);
                const r = await fetch('/login', {method: 'POST',
                    headers: {
                        'Content-Type': 'text/plain;charset=UTF-8',
                        'Next-Action': action,
                        'Next-Router-State-Tree': '[{"children":{"children":[{"segment":null,"children":"$@actions"}]},"segment":"login"}]',
                    },
                    body, credentials: 'include'});
                return {s: r.status, b: await r.text()};
            }""", [email, ACTION_SEND_MAGIC, tok])
            print(f"    resp: {r['b'][:200]}")
            if '"ok":true' not in r["b"].replace(" ", ""):
                log("    magic link FAIL (digest 500 = turnstile ditolak server)")
                return None

            log("[5] polling magic link (maks 3 menit)")
            link = tm_magic_link(mtok)
            if not link:
                return None

            log("[6] follow magic link")
            page.goto(link, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            log(f"    page: {page.title()}")

            log("[7] ambil API key")
            key = find_key(page)
            if not key:
                log("    key tidak ketemu di page/API — cek manual di dashboard")
                return None

            out = {"email": email, "key": key, "ts": int(time.time())}
            OUT.open("a").write(json.dumps(out) + "\n")
            log(f"[8] ✅ SUKSES")
            log(f"    KEY: {key}")
            return out
        except Exception as e:
            log(f"    ERR: {type(e).__name__}: {str(e)[:150]}")
            return None
        finally:
            try:
                ctx.close()
            except Exception:
                pass

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=1)
    args = ap.parse_args()

    ok = 0
    for i in range(args.loop):
        log(f"===== AKUN {i+1}/{args.loop} =====")
        if one_account():
            ok += 1
        if i < args.loop - 1:
            wait = random.randint(90, 240)
            log(f"tunggu {wait}s...")
            time.sleep(wait)
    log(f"===== SELESAI: {ok}/{args.loop} sukses =====")
    log(f"hasil: {OUT}")

if __name__ == "__main__":
    main()
