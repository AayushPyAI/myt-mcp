"""Rules every site script must keep (they run in the operator's Chrome, so they are checked here by reading their source)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.anyio

SITES = Path(__file__).parent.parent / "myt_mcp" / "sites"
GUARDED = ["getyourguide_activity", "getyourguide_find", "sata", "skyscanner", "tap", "viator_activity", "viator_find"]
FOOTER = "This site is protected by reCAPTCHA and the Google Privacy Policy and Terms of Service apply."


def _human_check(name: str) -> re.Pattern[str]:
    src = (SITES / f"{name}.js").read_text(encoding="utf-8")
    m = re.search(r"if \(/([^\n]*?captcha[^\n]*?)/i\.test", src)
    assert m, f"{name}.js has no human-check guard"
    return re.compile(m.group(1), re.I)


@pytest.mark.parametrize("name", GUARDED)
def test_the_recaptcha_footer_is_not_a_human_check(name):
    guard = _human_check(name)
    assert not guard.search(FOOTER)                         # SATA's footer made the script stop on a normal page (23 Oct 2026)
    assert guard.search("Please complete the CAPTCHA to continue")


def test_waits_stay_under_the_browser_tool_timeout():
    # the Chrome tool gives up after 45 s: a script that waits longer never returns its own message
    for name in ("tap", "sata"):
        src = (SITES / f"{name}.js").read_text(encoding="utf-8")
        loops = [int(n) for n in re.findall(r"for \(let i = 0; i < (\d+) &&[^\n]*await wait\(1000\)", src)]
        assert loops and max(loops) <= 40, name


# ---------- the wishes travel inside each script answer (23 Oct 2026: one `wishes` for four sources made a fare with no bag and no refund the 'Best fit') ----------

import json  # noqa: E402

from myt_mcp.sites import carried_wishes, convert_all, embed_wishes  # noqa: E402


def _tap_part(rows, wishes, run="r1", **extra):
    head = {"ok": True, "currency": "EUR", "pax": {"ADT": 2, "CHD": 1}, "not_available": False, "flights_total": 1, "offset": 0, "flights_in_part": 1, "page_direct": 1, "page_connecting": 0,
            "run": run, "rows_read": len(rows), "part": 1, "parts": 1, "rows": rows, "wishes": wishes, **extra}
    return json.dumps(head)


def _row(fare, total, bag, ref, fi):
    return {"fi": fi, "flights": "TP1865", "op": None, "from": "LIS", "to": "PDL", "dep": "2027-03-08 22:10", "arr": "2027-03-08 23:45", "stops": 0, "mins": 95, "via": "", "fare": fare, "cabin": "Economy",
            "total": total, "adt": total / 3, "chd": total / 3, "inf": None, "bag": bag, "ref": ref, "seats": 9}


def test_each_script_answer_is_judged_by_its_own_wishes_not_the_one_the_model_passed():
    tap_wishes = {"expect": {"origin": "LIS", "destination": "PDL", "day": "2027-03-08", "adults": 2, "children": 1, "infants": 0, "direct_only": True, "checked_bag": True, "refundable": True, "leg": "LIS to PDL"}}
    other_site_wishes = {"expect": {"origin": "LIS", "destination": "PDL", "day": "2027-03-08", "adults": 2, "children": 1, "direct_only": True}}      # what a recipe that never asks about bag or refund returns
    rows = [_row("DISCNEW", 209.04, 0, 0, 0), _row("PLUSNEW", 374.04, 1, 1, 1)]
    offers = convert_all([{"site": "tap", "result": _tap_part(rows, tap_wishes), "url": "u"}], other_site_wishes)[0]
    assert [o.fits for o in offers] == [False, True]                    # the no-bag, no-refund fare does not fit; it was 'Best fit' when the model's wishes won


def test_without_carried_wishes_the_passed_ones_are_still_used():
    passed = {"expect": {"origin": "LIS", "destination": "PDL", "day": "2027-03-08", "adults": 2, "children": 1, "direct_only": True, "checked_bag": True, "refundable": True}}
    part = json.loads(_tap_part([_row("DISCNEW", 209.04, 0, 0, 0)], {}))
    part.pop("wishes")
    offers = convert_all([{"site": "tap", "result": json.dumps(part), "url": "u"}], passed)[0]
    assert offers[0].fits is False


def test_carried_wishes_are_found_per_run_and_hold_the_filters():
    a = _tap_part([_row("A", 100, 1, 1, 0)], {"expect": {"direct_only": True}}, run="x", filters_used=["Direct flights only (operator)"])
    b = json.dumps({"ok": True, "run": "y", "rows": []})
    found = carried_wishes([{"site": "tap", "result": a}, {"site": "sata", "result": b}])
    assert list(found) == [("tap", "x")] and found[("tap", "x")]["filters_used"] == ["Direct flights only (operator)"]


def test_a_recipe_answer_puts_its_wishes_and_filters_into_its_script():
    out = embed_wishes({"script": "await (async () => {\n  return 1;\n})()", "wishes": {"expect": {"checked_bag": True}}, "filters_used": ["Fares with a checked bag only (operator)"]})
    assert out["script"].startswith("await (async () => {\n  const WISHES = {") and '"checked_bag": true' in out["script"] and "Fares with a checked bag only" in out["script"]
    plain = {"script": "await (async () => {\n})()"}
    assert embed_wishes(plain) is plain and "WISHES" not in plain["script"]       # no wishes, nothing to carry


async def test_every_registered_recipe_tool_carries_its_wishes():
    import re
    from mcp import Client
    from myt_mcp.app import create_server
    from myt_mcp.config import Settings
    from myt_mcp.services import Services
    settings = Settings()
    async with Client(create_server(settings, Services(settings))) as c:
        r = await c.call_tool("tap_recipe", {"origin": "LIS", "destination": "OPO", "day": "2027-03-08", "adults": 2, "children": 1, "direct_only": True, "checked_bag": True, "refundable": True})
        out = json.loads(r.content[0].text)
    m = re.search(r"const WISHES = (\{.*\});", out["script"])
    assert m and json.loads(m.group(1))["wishes"]["expect"]["refundable"] is True and "Direct flights only (operator)" in json.loads(m.group(1))["filters_used"]
    assert "typeof WISHES" in out["script"]                                # emit.js reads it into part 1


def test_in_myt_supplier_is_filled_from_the_local_directory_when_the_model_gives_none():
    from myt_mcp.compose import directory_status
    assert "supplier id 98430" in directory_status("TAP AIR PORTUGAL") and "yes" in directory_status("SATA Azores Airlines")
    assert directory_status("Nobody Air").startswith("not checked")          # not found there is never 'no'


# ---------- every part carries a checksum (a part passed through the model cannot be changed unseen) ----------

def _parts_from_emit(rows: list[dict]) -> list[str]:
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    emit_js = (SITES / "emit.js").read_text(encoding="utf-8")
    prog = ("globalThis.window = {}; globalThis.location = { href: 'https://example.com/x' };\n"
            "(async () => {\n" + emit_js + "\nemit({ ok: true, currency: 'EUR' }, " + json.dumps(rows, ensure_ascii=False) + ");\nconsole.log(JSON.stringify(window.__mytParts));\n})();")
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=60, check=True).stdout
    return json.loads(out)


def test_the_parts_the_script_makes_match_the_servers_checksum_and_a_changed_digit_is_caught():
    from myt_mcp.sites import check_parts, checksum_problem
    rows = [{"name": f"Hotel Açores {i} — café", "price": 100 + i * 1.5, "note": "ü" * 20} for i in range(120)]
    parts = _parts_from_emit(rows)
    assert len(parts) >= 2 and all(checksum_problem(p) is None for p in parts)
    items = [{"site": "ofran", "result": p} for p in parts]
    assert check_parts(items) == []
    typed = parts[1].replace("101.5", "101.4", 1) if "101.5" in parts[1] else parts[1].replace("1", "7", 1)
    assert typed != parts[1] and "checksum" in check_parts([items[0], {"site": "ofran", "result": typed}, *items[2:]])[0]
    cut = parts[0][:-3]
    assert "no checksum" in (checksum_problem(cut) or "")
    assert "no checksum" in (checksum_problem(re.sub(r',"crc":"[0-9a-f]{8}"', "", parts[0])) or "")


# ---------- a source whose parts keep failing is stopped, not re-run in a loop ----------

def _whole_part(site_run: str) -> str:
    import zlib
    text = json.dumps({"ok": True, "run": site_run, "rows_read": 0, "part": 1, "parts": 1, "cols": [], "common": {}, "path_base": "", "rows": []})
    return text[:-1] + ',"crc":"' + format(zlib.crc32(text.encode("utf-8")), "08x") + '"}'


def test_parts_that_fail_twice_make_the_server_say_stop_and_a_whole_pass_starts_the_count_again():
    from myt_mcp.sites import check_parts
    broken = [{"site": "ratehawk_hotels", "result": '{"run":"a","part":1,"parts":2,"rows":[]}'}]
    first = check_parts(broken)
    assert first and not any("STOP" in p for p in first) and "received" in first[0] and "characters" in first[0]
    second = check_parts(broken)
    assert any("STOP" in p and "not_checked" in p and "ratehawk_hotels" in p for p in second)
    assert check_parts([{"site": "ratehawk_hotels", "result": _whole_part("b")}]) == []         # whole: the count is cleared
    assert not any("STOP" in p for p in check_parts(broken))
    other = check_parts([{"site": "getyourguide_find", "result": '{"run":"c","part":1,"parts":2,"rows":[]}'}])
    assert not any("STOP" in p for p in other)               # another site has its own count
