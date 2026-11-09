"""RateHawk hotels' answer in SLIM parts (29 Oct 2026): the page's security policy stops the post, the browser tool shows the model about 1,000 characters, so every part must fit in ONE output.
The server joins the parts of a run and reads them like the old format: the same offers come out."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from myt_mcp.ingest import STORE
from myt_mcp.sites import check_parts, checksum_problem, convert_all, embed_wishes, join_slim_parts

SITES = Path(__file__).resolve().parent.parent / "myt_mcp" / "sites"
HEAD = {"ok": True, "next": "STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.",
        "check_in": "2027-03-06", "check_out": "2027-03-13", "adults": 2, "child_ages": [], "residency": "en-il", "sort": "price_asc", "filters": {"stars": [40, 50], "free_cancellation": True, "meals": ["breakfast"]},
        "offset": 0, "results_total": 255, "search_finished": True, "page_header_count": 255}
NAMES = ["Czar Lisbon Hotel", "Hotel 3K Madrid", "Flores Guest House", "Quinta Colina by Shiadu", "Lisbon Arsenal Suites", "Casa do Patio by Shiadu", "Casa do Bairro by Shiadu", "Casa Das Janelas Com Vista"]
WISHES = {"breakfast": True, "free_cancellation": True, "stars_min": 4, "max_distance_km": 2.0, "max_total": 1050}
FILTERS = ["Breakfast included (operator)", "Free cancellation (operator)", "4+ stars (operator)", "within 2 km of the centre (operator)"]


def _rows(n=30, nbsp=False):
    sp = "\u00a0" if nbsp else " "
    return [{"p": 1 if i < 20 else 2, "rank": i + 1, "name": f"{NAMES[i % 8]}{sp}{i}", "kind": "Hotel", "stars": 4, "dist_km": round(0.4 + i * 0.05, 2), "score": 8 + (i % 10) / 10, "reviews": 100 + i * 37,
             "room": "Standard Double room (full double bed)", "meal": ["breakfast"], "free_before": "2027-03-04T00:00:00Z", "penalty": [], "pay": "deposit", "amount": 510 + i * 9, "cur": "EUR", "per_night": (510 + i * 9) / 7,
             "taxes_extra": [], "left": None, "path": f"/hotel/portugal/lisbon/mid{7765798 + i * 13}/{NAMES[i % 8].lower().replace(' ', '_')}/"} for i in range(n)]


def _node_parts(rows, prelude=""):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    prog = ("globalThis.window = { innerWidth: 1440 }; globalThis.location = { href: 'https://example.com/x' };\n(async () => {\n" + prelude + (SITES / "emit.js").read_text(encoding="utf-8")
            + "\nemit(" + json.dumps(HEAD) + ", " + json.dumps(rows, ensure_ascii=False) + ");\nconsole.log(JSON.stringify(window.__mytParts));\n})();")
    return json.loads(subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=60, check=True).stdout)


def _slim(rows):
    token = STORE.new_run("ratehawk_hotels", dict(WISHES), list(FILTERS))
    return _node_parts(rows, f"const SLIM = true; const WK = {json.dumps(token)};\n"), token


def _old(rows):
    return _node_parts(rows, "const WISHES = " + json.dumps({"wishes": WISHES, "filters_used": FILTERS}) + ";\n")


def _items(parts):
    return [{"site": "ratehawk_hotels", "result": p, "url": "https://rh.test/list"} for p in parts]


def test_every_slim_part_fits_in_one_tool_output_and_the_old_parts_did_not():
    old = _old(_rows())
    slim, _ = _slim(_rows())
    assert max(len(p) for p in old) > 2000 and len(old) <= 3
    assert len(slim) >= 5 and all(len(p) <= 850 for p in slim) and all(p.isascii() for p in slim)         # the browser tool shows about 1,000 characters
    assert all(checksum_problem(p) is None for p in slim) and check_parts(_items(slim)) == []
    first = json.loads(slim[0])
    assert first["fmt"] == "slim" and first["part"] == 1 and first["parts"] == len(slim) and first["wk"] and first["viewport"] == 1440 and "wishes" not in first and "filters_used" not in first
    assert all(set(json.loads(p)) == {"fmt", "run", "part", "parts", "rows", "crc"} for p in slim[1:])      # the other parts carry only their rows


def _shape(offers):
    return [(o.name, o.price_total, o.currency, o.price_basis, o.fits, o.flexible, o.link, o.details) for o in offers]


def test_the_server_reads_slim_parts_into_the_same_offers_as_the_old_format():
    rows = _rows()
    old_offers, old_sources, old_problems, old_by_price, _ = convert_all(_items(_old(rows)), None)
    slim, _ = _slim(rows)
    new_offers, new_sources, new_problems, new_by_price, _ = convert_all(_items(slim), None)
    assert not old_problems and not new_problems, (old_problems, new_problems)
    assert len(new_offers) == 30 and _shape(new_offers) == _shape(old_offers) and new_by_price == old_by_price
    assert (new_sources[0].read, new_sources[0].of) == (old_sources[0].read, old_sources[0].of)


def test_the_wishes_of_a_slim_run_come_from_the_server_by_its_token_and_a_forgotten_token_does_not_break_it():
    from myt_mcp.sites import carried_wishes
    slim, token = _slim(_rows(12))
    got = list(carried_wishes(_items(slim)).values())
    assert len(got) == 1 and got[0]["wishes"]["stars_min"] == 4 and got[0]["filters_used"] == FILTERS
    joined = join_slim_parts(_items(slim))
    assert len(joined) == 1 and joined[0]["wishes"]["max_total"] == 1050 and json.loads(joined[0]["result"])["rows_read"] == 12 and "cols" not in json.loads(joined[0]["result"])
    STORE.clear()                                                                       # the token is gone (the server was restarted): the wishes compose_answer was given still apply
    offers, _, problems, _, _ = convert_all(_items(slim), WISHES)
    assert len(offers) == 12 and not problems
    assert convert_all(_items(slim), None)[2] == []      # no wishes at all: nothing to check the search against


def test_a_slim_run_with_a_part_missing_says_which_one_and_gives_no_half_answer():
    slim, _ = _slim(_rows())
    short = _items(slim[:2] + slim[3:])
    problems = check_parts(short)
    assert any("part(s) 3 of" in p and "missing" in p for p in problems)
    offers, _, more, _, _ = convert_all(short, None)
    assert offers == [] and any("missing" in p for p in more)


def test_a_slim_part_typed_back_with_real_characters_is_repaired_and_a_changed_digit_is_caught():
    slim, _ = _slim(_rows(nbsp=True))
    assert any("\\u00a0" in p for p in slim)
    typed = [re.sub(r"\\u([0-9a-f]{4})", lambda m: chr(int(m.group(1), 16)), p) if i == 1 else p for i, p in enumerate(slim)]      # the assistant wrote the character, not its escape
    assert typed[1] != slim[1]
    items = _items(typed)
    offers, _, problems, _, _ = convert_all(items, None)
    assert not problems and len(offers) == 30 and offers[0].name == "Czar Lisbon Hotel\u00a00"
    assert items[1]["result"] == slim[1]                                                # the exact text the script made went on
    broken = _items([slim[0], slim[1].replace(",510,", ",610,", 1)] + slim[2:])
    assert any("checksum" in p for p in check_parts(broken))


def test_every_page_that_cannot_post_is_slim_and_a_page_that_posts_is_not():
    import myt_mcp.sites as sites
    head = "await (async () => {\n"
    original = sites.public_base
    sites.public_base = lambda: "https://example.test"
    try:
        slim = {site: sites.embed_wishes({"script": head + "return 1;", "wishes": {"x": 1}, "filters_used": []}, site) for site in sorted(sites.NO_POST)}
        posting = sites.embed_wishes({"script": head + "return 1;", "wishes": {"x": 1}, "filters_used": []}, "arbitrip_hotels")
    finally:
        sites.public_base = original
    assert sites.SLIM_SITES == sites.NO_POST and {"getyourguide_find", "viator_find", "cp_trains", "sata", "ratehawk_hotels"} <= sites.SLIM_SITES
    assert all("const SLIM = true" in o["script"] and "const WK = " in o["script"] and "const WISHES" not in o["script"] for o in slim.values())
    assert "const INGEST" in posting["script"] and "const SLIM" not in posting["script"]


def test_long_head_texts_go_in_parts_of_their_own_and_come_back_whole():
    """2 Nov 2026: Viator's page answer had 1,000+ characters of head text (included, meeting point, cancellation): part 1 was 1,168 characters, the browser tool cut it and the chat rebuilt it by hand."""
    head = {**HEAD, "url_path": "/Lisbon/d538-5731P2", "activity": "Lisbon Food and Wine Tour", "options_found": 2,
            "included": "Food and drinks as listed. " * 9, "meeting_text": "Meet at Praça Dom Pedro IV (Rossio) by the statue, 1100-202 Lisboa — ז" * 5, "cancel_policy": "Free cancellation up to 24 hours before the start. " * 5}
    rows = [{"title": "Standard group", "price": "EUR 158", "time": "10:30"}, {"title": "Private", "price": "EUR 340", "time": "11:00"}]
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    token = STORE.new_run("viator_activity", {"expect": {"x": 1}}, None)
    prog = ("globalThis.window = { innerWidth: 1440 }; globalThis.location = { href: 'https://example.com/x' };\n(async () => {\nconst SLIM = true; const WK = " + json.dumps(token) + ";\n" + (SITES / "emit.js").read_text(encoding="utf-8")
            + "\nemit(" + json.dumps(head, ensure_ascii=False) + ", " + json.dumps(rows) + ");\nconsole.log(JSON.stringify(window.__mytParts));\n})();")
    parts = json.loads(subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=60, check=True).stdout)
    assert all(len(p) <= 850 and p.isascii() for p in parts) and len(parts) >= 3
    first = json.loads(parts[0])
    assert first["part"] == 1 and set(first["hn"]) == {"included", "meeting_text", "cancel_policy"} and "included" not in first and len(first["rows"]) == 2
    items = [{"site": "viator_activity", "result": p, "url": "https://viator.test/x"} for p in parts]
    assert check_parts(items) == []
    joined = json.loads(join_slim_parts(items)[0]["result"])
    assert (joined["included"], joined["meeting_text"], joined["cancel_policy"]) == (head["included"], head["meeting_text"], head["cancel_policy"])
    assert joined["rows"] == rows and "hn" not in joined and "hx" not in joined
