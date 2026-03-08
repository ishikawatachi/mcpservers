#!/usr/bin/env python3
"""
Test script: Scan https://wazuh.local.defaultvaluation.com/app/login
and verify the i18n error is gone (server-side checks).

Checks:
  1. Login page returns HTTP 200
  2. Server embeds correct translationsUrl in HTML metadata
  3. translationsUrl returns valid locale ("en") and messages
  4. No indication of empty/missing locale
  5. /api/status reachable (server healthy)

Usage: python3 _test_wazuh_ui.py
"""
import json, ssl, re, sys, html as hlib
import urllib.request, urllib.error

BASE = "https://wazuh.local.defaultvaluation.com"
EXPECTED_LOCALE = "en"

def ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c

def fetch(url, headers=None, timeout=10):
    req = urllib.request.Request(url, headers=headers or {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X)",
        "Accept": "*/*",
    })
    try:
        with urllib.request.urlopen(req, context=ctx(), timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), {}
    except Exception as e:
        return None, str(e), {}

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"

results = []

def check(name, passed, detail="", warn=False):
    icon = PASS if passed else (WARN if warn else FAIL)
    tag = "PASS" if passed else ("WARN" if warn else "FAIL")
    print(f"  [{icon}] {name}")
    if detail:
        print(f"         → {detail}")
    results.append((name, tag))
    return passed

print("=" * 62)
print(f"  Wazuh UI Test: {BASE}/app/login")
print("=" * 62)

# ── Check 1: Login page HTTP 200 ─────────────────────────────────
print("\n[1] Login page accessibility")
status, body, headers = fetch(f"{BASE}/app/login")
if status is None:
    check("Login page reachable", False, f"Network error: {body}")
    sys.exit(1)
check("HTTP 200 response", status == 200, f"Got HTTP {status}")

# ── Check 2: osd-injected-metadata present ───────────────────────
print("\n[2] Server-injected metadata")
decoded_body = hlib.unescape(body)

# Look for the i18n section in decoded HTML
m_i18n = re.search(r'"i18n"\s*:\s*\{[^}]*"translationsUrl"\s*:\s*"([^"]+)"', decoded_body)
if m_i18n:
    translations_url = m_i18n.group(1)
    check("i18n section present", True, f"translationsUrl = {translations_url!r}")
    translations_ok = True
else:
    # Try HTML-encoded search
    m_enc = re.search(r'translationsUrl', body)
    translations_url = None
    check("i18n section present", False,
          "osd-injected-metadata contains no translationsUrl" if not m_enc
          else "translationsUrl found but couldn't extract value — may be encoded")
    translations_ok = False

if translations_url:
    # Verify the URL looks correct (should end with /en.json or similar)
    check("translationsUrl has non-empty locale",
          bool(translations_url) and "/translations/." not in translations_url
          and "undefined" not in translations_url,
          f"URL: {translations_url}")

    # ── Check 3: Fetch translations endpoint ─────────────────────
    print("\n[3] Translations endpoint")
    trans_full_url = f"{BASE}{translations_url}" if translations_url.startswith("/") else translations_url
    status2, body2, _ = fetch(trans_full_url)
    check("translationsUrl returns HTTP 200", status2 == 200, f"Got HTTP {status2}")
    if status2 == 200:
        try:
            trans_data = json.loads(body2)
            locale_val = trans_data.get("locale", "")
            check("locale field present and non-empty",
                  bool(locale_val),
                  f"locale={locale_val!r}")
            check(f"locale matches expected ({EXPECTED_LOCALE!r})",
                  locale_val == EXPECTED_LOCALE,
                  f"got {locale_val!r}")
            check("messages field present",
                  "messages" in trans_data,
                  f"messages={'present' if 'messages' in trans_data else 'MISSING'}")
        except json.JSONDecodeError as e:
            check("translations JSON parseable", False, f"JSON error: {e}")
            check("locale field present", False, "N/A — bad JSON")
    else:
        check("locale field present", False, "N/A — request failed")

# ── Check 4: Look for error indicators in HTML ───────────────────
print("\n[4] HTML error indicators")
error_indicators = [
    "A locale must be a non-empty string",
    "server error",
    "Internal Server Error",
]
found_errors = [e for e in error_indicators if e.lower() in body.lower()]
check("No known i18n error strings in login HTML",
      len(found_errors) == 0,
      f"Found: {found_errors}" if found_errors else "Clean")

# ── Check 5: /api/status ─────────────────────────────────────────
print("\n[5] Server health")
status3, body3, _ = fetch(f"{BASE}/api/status")
if status3 == 401:
    # 401 is expected — the server is running and requiring authentication
    check("API status reachable (auth-protected)", True,
          "HTTP 401 — server is up, authentication required (expected)")
elif status3 == 200:
    try:
        api_data = json.loads(body3)
        overall = api_data.get("status", {}).get("overall", {}).get("state", "unknown")
        check("API status reachable", True, f"overall state: {overall!r}")
        check("API state is 'green'", overall == "green",
              f"state={overall!r}", warn=(overall != "green"))
    except json.JSONDecodeError:
        check("API status reachable", True, warn=True,
              detail="HTTP 200 but non-JSON response")
elif status3 in (302, 303):
    check("API status reachable", True, warn=True,
          detail=f"HTTP {status3} redirect (authentication redirect — server is up)")
else:
    check("API status reachable", False, f"HTTP {status3}")

# ── Summary ───────────────────────────────────────────────────────
print("\n" + "=" * 62)
failures = [n for n, r in results if r == "FAIL"]
warnings = [n for n, r in results if r == "WARN"]
passes = [n for n, r in results if r == "PASS"]
total = len(results)

print(f"  Results: {len(passes)}/{total} passed", end="")
if warnings: print(f", {len(warnings)} warning(s)", end="")
if failures: print(f", {len(failures)} failure(s)", end="")
print()

if not failures:
    print()
    print("  \033[32m✓ Server-side i18n configuration is CORRECT.\033[0m")
    print("  The [I18n] error is likely a browser cache artifact.")
    print()
    print("  ACTION REQUIRED: Do a hard refresh in your browser:")
    print("    Mac:     Cmd + Shift + R")
    print("    Windows: Ctrl + Shift + R")
    print("    Or:      Open in a private/incognito window first")
    print()
    if warnings:
        print("  Warnings:")
        for w in warnings:
            print(f"    - {w}")
else:
    print()
    print("  \033[31m✗ Issues found — see FAIL items above.\033[0m")
    print()
    print("  Failed checks:")
    for f in failures:
        print(f"    - {f}")

print("=" * 62)
