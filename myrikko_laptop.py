#!/usr/bin/env python3
"""
Myrikko $10-bonus farm — LAPTOP edition (real Chrome, residential IP).

Setup (sekali):
  pip install playwright requests
  python myrikko_laptop.py

Pakai:
  python myrikko_laptop.py            # 1 akun
  python myrikko_laptop.py --loop 5   # 5 akun berurutan
  python myrikko_laptop.py --aff XXX  # pakai referral code

Rules:
  - WiFi rumah, VPN/HOTSPOT OFF (IP rumah = residential = Turnstile auto-pass)
  - Chrome akan kebuka sendiri, BIARKAN terlihat (jangan minimize)
  - Hasil masuk ke myrikko_accounts.jsonl + printed di terminal
"""
import argparse, json, random, re, sys, time, uuid
from datetime import datetime
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

SITEKEY = "0x4AAAAAAEttvBixKhfJewXu"
BASE = "https://myrikko.ai"
OUT = Path(__file__).parent / "myrikko_accounts.jsonl"

def log(m):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

def _http(method, url, body=None, token=None, timeout=25):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.request(method, url, json=body, headers=headers, timeout=timeout)
    try:
        return r.json()
    except Exception:
        return {"_status": r.status_code, "_text": r.text[:300]}

def tm_create():
    doms = _http("GET", "https://api.mail.tm/domains")["hydra:member"]
    dom = random.choice(doms)["domain"]
    addr = f"myk{random.randint(10**7, 10**8 - 1)}@{dom}"
    pw = "Px" + uuid.uuid4().hex[:8] + "!1"
    _http("POST", "https://api.mail.tm/accounts", {"address": addr, "password": pw})
    tok = _http("POST", "https://api.mail.tm/token", {"address": addr, "password": pw})["token"]
    return addr, tok

def tm_otp(tok, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            msgs = _http("GET", "https://api.mail.tm/messages?page=1", token=tok).get("hydra:member", [])
            for m in msgs:
                full = _http("GET", f"https://api.mail.tm/messages/{m['id']}", token=tok)
                codes = re.findall(r"\b(\d{6})\b", full.get("text", "") or full.get("intro", ""))
                if codes:
                    return codes[0]
        except Exception:
            pass
        time.sleep(5)
    return None

RENDER = """
async (sitekey) => {
  if (!window.turnstile) {
    await new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
      s.async = true; s.onload = resolve; s.onerror = () => reject(new Error('api.js load fail'));
      document.head.appendChild(s);
    });
    for (let i = 0; i < 100 && !window.turnstile; i++) await new Promise(r => setTimeout(r, 100));
  }
  if (!window.turnstile) return {ok:false, stage:'no-api'};
  let box = document.getElementById('ts-box');
  if (!box) { box = document.createElement('div'); box.id='ts-box'; document.body.prepend(box); }
  else box.innerHTML = '';
  window.__ts_token = ''; window.__ts_err = '';
  try {
    const wid = window.turnstile.render(box, {sitekey,
      callback: t => { window.__ts_token = t; },
      'error-callback': e => { window.__ts_err = String(e); }});
    return {ok:true, widgetId:String(wid)};
  } catch(e) { return {ok:false, stage:'render-err:'+e.message}; }
}
"""

def mint_token(page):
    """Force-render Turnstile + tunggu token (residential IP = biasanya <10s)."""
    for att in range(3):
        res = page.evaluate(RENDER, SITEKEY)
        if not res.get("ok"):
            log(f"  render fail: {res}")
            time.sleep(3)
            continue
        for i in range(60):
            t = page.evaluate("() => window.__ts_token || ''")
            e = page.evaluate("() => window.__ts_err || ''")
            if len(t) > 50:
                log(f"  token OK ({len(t)} chars, {i+1}s)")
                return t
            if e:
                log(f"  ts error: {e}")
                break
            time.sleep(1)
        # reset widget lalu retry
        try:
            page.evaluate("() => { try { turnstile.remove(window.__wid) } catch(e) {} }")
        except Exception:
            pass
    return None

def launch_browser(p):
    """Real Chrome (bukan headless). Fallback: Edge -> bundled Chromium."""
    ctx = None
    for channel in ("chrome", "msedge", None):
        try:
            kw = {"headless": False, "args": ["--window-size=1100,800"]}
            if channel:
                kw["channel"] = channel
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(Path(__file__).parent / ".chrome-profile"),
                viewport={"width": 1100, "height": 800},
                **kw,
            )
            log(f"browser: {channel or 'chromium'} OK")
            return ctx
        except Exception as e:
            log(f"browser {channel}: {str(e)[:60]}")
    raise RuntimeError("gak ada browser yang bisa dibuka")

def one_account(aff=""):
    with sync_playwright() as p:
        ctx = launch_browser(p)
        page = ctx.new_page()
        try:
            log("[1] buka register page")
            page.goto(f"{BASE}/register", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)

            log("[2] mint Turnstile token #1")
            tok1 = mint_token(page)
            if not tok1:
                return None

            log("[3] bikin email temp + minta OTP")
            email, mtok = tm_create()
            log(f"    email: {email}")
            r = page.evaluate("""async ([email, tok]) => {
                const r = await fetch('/api/verification', {method:'POST',
                    headers:{'Content-Type':'application/json','X-Turnstile-Token':tok},
                    body: JSON.stringify({email}), credentials:'include'});
                return {s:r.status, b:await r.text()};
            }""", [email, tok1])
            log(f"    verification: {r['b'][:120]}")
            if '"success":true' not in r["b"]:
                return None

            log("[4] polling OTP (maks 3 menit)")
            code = tm_otp(mtok)
            if not code:
                log("    OTP gak datang")
                return None
            log(f"    OTP: {code}")

            log("[5] mint token #2 + register")
            tok2 = mint_token(page)
            if not tok2:
                return None
            password = "@Asikin123"
            r = page.evaluate("""async ([email, password, code, tok, aff]) => {
                const r = await fetch('/api/user/register/v2', {method:'POST',
                    headers:{'Content-Type':'application/json','X-Turnstile-Token':tok},
                    body: JSON.stringify({email, password, verification_code:code,
                        aff_code:aff, utm_params:{}, session_id:crypto.randomUUID()}),
                    credentials:'include'});
                return {s:r.status, b:await r.text()};
            }""", [email, password, code, tok2, aff])
            log(f"    register: {r['b'][:200]}")
            try:
                uid = json.loads(r["b"])["data"]["id"]
            except Exception:
                return None

            log("[6] create default token + claim bonus $10")
            r3 = page.evaluate("""async (uid) => {
                const h = {'New-Api-User': String(uid)};
                const t = await fetch('/api/token/default', {headers:h, credentials:'include'});
                const c = await fetch('/api/user/claim-signup-bonus', {method:'POST', headers:h, credentials:'include'});
                return {token: await t.text(), claim: await c.text()};
            }""", uid)
            try:
                key = json.loads(r3["token"])["data"]["key"]
            except Exception:
                key = ""
            log(f"    claim: {r3['claim'][:80]}")

            out = {"email": email, "password": password, "uid": uid, "key": key,
                   "ts": int(time.time())}
            OUT.open("a").write(json.dumps(out) + "\n")
            log(f"[7] ✅ SUKSES — {email}")
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
    ap.add_argument("--aff", default="")
    args = ap.parse_args()

    ok = 0
    for i in range(args.loop):
        log(f"===== AKUN {i+1}/{args.loop} =====")
        if one_account(args.aff):
            ok += 1
        if i < args.loop - 1:
            wait = random.randint(60, 150)
            log(f"tunggu {wait}s sebelum akun berikutnya...")
            time.sleep(wait)
    log(f"===== SELESAI: {ok}/{args.loop} sukses =====")
    log(f"hasil lengkap: {OUT}")

if __name__ == "__main__":
    main()
