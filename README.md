# myrikko-farm

Automated Myrikko.ai account registration + $10 signup bonus claim.

## Why this exists

Myrikko.ai gives every new account a **$10 signup bonus**. This tool automates the whole flow end-to-end:

1. Real Chrome opens `myrikko.ai/register`
2. Cloudflare Turnstile is force-rendered and **auto-solved** (works on residential IPs — laptop/home WiFi)
3. Temp email is created via `mail.tm`
4. OTP is polled automatically
5. Account is registered via `/api/user/register/v2`
6. Bonus is claimed via `/api/user/claim-signup-bonus`
7. API key is printed and saved to `myrikko_accounts.jsonl`

## Install

```bash
pip install playwright requests
playwright install chromium
```

## Usage

```bash
# 1 account
python myrikko_laptop.py

# 5 accounts with random 1-2 min gaps
python myrikko_laptop.py --loop 5

# with referral code
python myrikko_laptop.py --aff YOURCODE
```

## Requirements

- Python 3.9+
- A **residential IP** (home WiFi). Turnstile silently refuses datacenter IPs
  (VPS, WARP, most proxies). Do NOT run with VPN/hotspot on.
- Chrome (used instead of bundled Chromium automatically when present)

## Output

Each success appends a JSON line to `myrikko_accounts.jsonl`:

```json
{"email": "...", "password": "@Asikin123", "uid": 12345, "key": "sk-...", "ts": 1726740000}
```

## Lessons learned (VPS attempts)

| Path | Result |
|------|--------|
| VPS1 direct IP | ❌ Turnstile silent-refuse (datacenter ASN burned) |
| VPS1 + WARP (IPv4/IPv6) | ❌ widget renders, iframe never injected |
| VPS1 + residential HTTP proxy | ❌ proxy drops `challenges.cloudflare.com` per-session |
| Headed Xvfb | ❌ same as headless |
| Laptop / phone residential IP | ✅ expected to work — Turnstile trusts residential |

The "silent refuse" signature: `window.turnstile` loads, `turnstile.render()`
returns a widgetId, but the challenge iframe is never injected into the DOM and
no token or error ever arrives.

## Disclaimer

For educational/testing purposes. Respect myrikko.ai's terms of service.
