"""Full Polymarket API verification script"""
import sys
import time
import traceback
import os
os.environ["PYTHONUNBUFFERED"] = "1"

sys.path.insert(0, ".")
from dr_manhattan.exchanges.polymarket import Polymarket

TEST_ADDRESS = "0x56687bf447db6ffa42ffe2204a05edaa20f55839"

pm = Polymarket({"verbose": False})

results = {"ok": [], "partial": [], "fail": [], "auth": []}

def test(name, fn):
    try:
        r = fn()
        desc = str(type(r).__name__)
        if isinstance(r, list):
            desc = f"list[{len(r)}]"
        elif isinstance(r, dict):
            keys = list(r.keys())[:5]
            desc = f"dict keys={keys}"
        elif isinstance(r, bytes):
            desc = f"bytes[{len(r)}]"
        results["ok"].append(f"{name}: {desc}")
        print(f"  ✅ {name}: {desc}")
        return r
    except Exception as e:
        err = str(e)[:120]
        if "401" in err or "auth" in err.lower():
            results["auth"].append(f"{name}: {err}")
            print(f"  🔒 {name}: {err}")
        else:
            results["fail"].append(f"{name}: {err}")
            print(f"  ❌ {name}: {err}")
        return None

# ============================================================
# GAMMA
# ============================================================
print("\n=== GAMMA API ===")
test("get_gamma_status", lambda: pm.get_gamma_status())

markets = test("fetch_markets(limit=3)", lambda: pm.fetch_markets({"limit": 3}))

# Get IDs for further tests
market_id = None
condition_id = None
token_ids = []
event_id = None
if markets and len(markets) > 0:
    m = markets[0]
    market_id = m.id
    condition_id = m.metadata.get("condition_id", m.id)
    token_ids = m.metadata.get("clobTokenIds", [])
    print(f"  → market_id={market_id}, tokens={token_ids[:2]}")

test("fetch_market(market_id)", lambda: pm.fetch_market(market_id) if market_id else (_ for _ in ()).throw(Exception("no market_id")))

# Get a slug from events
events = test("fetch_events(limit=5)", lambda: pm.fetch_events(limit=5))
if events and len(events) > 0:
    event_id = events[0].get("id")
    event_slug = events[0].get("slug", "")
    print(f"  → event_id={event_id}, slug={event_slug}")

    test("fetch_event(event_id)", lambda: pm.fetch_event(str(event_id)))
    if event_slug:
        test("fetch_event_by_slug(slug)", lambda: pm.fetch_event_by_slug(event_slug))

# fetch_markets_by_slug - need a real slug
if event_slug:
    test("fetch_markets_by_slug(slug)", lambda: pm.fetch_markets_by_slug(event_slug))

test("search_markets(query='bitcoin', limit=5)", lambda: pm.search_markets(limit=5, query="bitcoin"))

series = test("fetch_series(limit=3)", lambda: pm.fetch_series(limit=3))
series_id = None
if series and len(series) > 0:
    series_id = series[0].get("id")
    print(f"  → series_id={series_id}")
    test("fetch_series_by_id(series_id)", lambda: pm.fetch_series_by_id(str(series_id)))

tags = test("fetch_tags(limit=5)", lambda: pm.fetch_tags(limit=5))
tag_id = None
if tags and len(tags) > 0:
    tag_id = tags[0].get("id")
    print(f"  → tag_id={tag_id}")
    test("fetch_tag_by_id(tag_id)", lambda: pm.fetch_tag_by_id(str(tag_id)))

test("get_tag_by_slug('politics')", lambda: pm.get_tag_by_slug("politics"))

if market_id:
    test("fetch_market_tags(market_id)", lambda: pm.fetch_market_tags(str(market_id)))

if event_id:
    test("fetch_event_tags(event_id)", lambda: pm.fetch_event_tags(str(event_id)))

test("fetch_sports_metadata", lambda: pm.fetch_sports_metadata())
test("fetch_sports_market_types", lambda: pm.fetch_sports_market_types())

# comments - try with a market id
if market_id:
    test("fetch_comments(market_id)", lambda: pm.fetch_comments(str(market_id), entity_type="market", limit=5))

test("fetch_profile(address)", lambda: pm.fetch_profile(TEST_ADDRESS))

# ============================================================
# CLOB
# ============================================================
print("\n=== CLOB API ===")

if token_ids and len(token_ids) > 0:
    tid = token_ids[0]
    test("get_orderbook(token_id)", lambda: pm.get_orderbook(tid))
    if len(token_ids) >= 2:
        test("get_orderbooks([t1,t2])", lambda: pm.get_orderbooks(token_ids[:2]))
    test("get_price(token_id)", lambda: pm.get_price(tid))
    if len(token_ids) >= 2:
        test("get_prices([t1,t2])", lambda: pm.get_prices(token_ids[:2]))
    test("get_midpoint(token_id)", lambda: pm.get_midpoint(tid))
    if len(token_ids) >= 2:
        test("get_spreads([t1,t2])", lambda: pm.get_spreads(token_ids[:2]))
else:
    print("  ⚠️ No token_ids available for CLOB tests")

# fetch_price_history - needs a Market object with token IDs
if markets and len(markets) > 0:
    test("fetch_price_history(market, limit)", lambda: pm.fetch_price_history(markets[0], interval="1d", fidelity=5))

if condition_id:
    test("fetch_token_ids(condition_id)", lambda: pm.fetch_token_ids(condition_id))

# ============================================================
# DATA API
# ============================================================
print("\n=== DATA API ===")
test("fetch_public_trades(limit=5)", lambda: pm.fetch_public_trades(limit=5))
test("fetch_leaderboard(limit=5)", lambda: pm.fetch_leaderboard(limit=5))
test("fetch_user_activity(addr, limit=5)", lambda: pm.fetch_user_activity(TEST_ADDRESS, limit=5))

if condition_id:
    test("fetch_top_holders(cid, limit=5)", lambda: pm.fetch_top_holders(condition_id, limit=5))
    test("fetch_open_interest(cid)", lambda: pm.fetch_open_interest(condition_id))

test("fetch_closed_positions(addr, limit=5)", lambda: pm.fetch_closed_positions(TEST_ADDRESS, limit=5))
test("fetch_positions_data(addr, limit=5)", lambda: pm.fetch_positions_data(TEST_ADDRESS, limit=5))
test("fetch_portfolio_value(addr)", lambda: pm.fetch_portfolio_value(TEST_ADDRESS))

if event_id:
    test("fetch_live_volume(event_id)", lambda: pm.fetch_live_volume(int(event_id)))

test("fetch_traded_count(addr)", lambda: pm.fetch_traded_count(TEST_ADDRESS))
test("fetch_builder_leaderboard(limit=5)", lambda: pm.fetch_builder_leaderboard(limit=5))

# builder_volume - need a builder_id from leaderboard
builder_lb = pm.fetch_builder_leaderboard(limit=1)
if builder_lb and len(builder_lb) > 0:
    bid = builder_lb[0].get("builderId", builder_lb[0].get("id", ""))
    if bid:
        test("fetch_builder_volume(builder_id)", lambda: pm.fetch_builder_volume(str(bid)))
    else:
        print(f"  ⚠️ builder_leaderboard keys: {list(builder_lb[0].keys())}")

test("fetch_accounting_snapshot(addr)", lambda: pm.fetch_accounting_snapshot(TEST_ADDRESS))

# ============================================================
# BRIDGE
# ============================================================
print("\n=== BRIDGE API ===")
test("fetch_supported_assets", lambda: pm.fetch_supported_assets())
test("fetch_bridge_status(addr)", lambda: pm.fetch_bridge_status(TEST_ADDRESS))

# ============================================================
# CTF (import only)
# ============================================================
print("\n=== CTF (import check) ===")
for method_name in ["split", "merge", "redeem", "redeem_all", "fetch_redeemable_positions"]:
    if hasattr(pm, method_name):
        results["auth"].append(f"{method_name}: import OK (requires auth)")
        print(f"  🔒 {method_name}: import OK (requires auth)")
    else:
        results["fail"].append(f"{method_name}: method not found")
        print(f"  ❌ {method_name}: method not found")

# ============================================================
# PAGINATION
# ============================================================
print("\n=== PAGINATION VERIFICATION ===")

def test_pagination(name, fn3, fn10, fn_offset3=None):
    try:
        r3 = fn3()
        r10 = fn10()
        l3, l10 = len(r3), len(r10)
        msg = f"limit=3→{l3}, limit=10→{l10}"
        
        if fn_offset3:
            r_off = fn_offset3()
            # Check if offset results differ from first page
            if isinstance(r3, list) and isinstance(r_off, list) and len(r3) > 0 and len(r_off) > 0:
                # Compare first items
                first_page_ids = set()
                second_page_ids = set()
                for item in r3:
                    if isinstance(item, dict):
                        first_page_ids.add(str(item.get("id", item.get("transactionHash", ""))))
                    else:
                        first_page_ids.add(str(getattr(item, "id", getattr(item, "transaction_hash", ""))))
                for item in r_off:
                    if isinstance(item, dict):
                        second_page_ids.add(str(item.get("id", item.get("transactionHash", ""))))
                    else:
                        second_page_ids.add(str(getattr(item, "id", getattr(item, "transaction_hash", ""))))
                overlap = first_page_ids & second_page_ids
                if not overlap or overlap == {""}:
                    msg += ", offset ✅"
                else:
                    msg += f", offset ⚠️ overlap={len(overlap)}"
            else:
                msg += ", offset checked"

        ok = l3 <= 3 and l10 <= 10 and l10 >= l3
        status = "✅" if ok else "⚠️"
        print(f"  {status} {name}: {msg}")
        results["ok" if ok else "partial"].append(f"pagination_{name}: {msg}")
    except Exception as e:
        err = str(e)[:100]
        print(f"  ❌ {name}: {err}")
        results["fail"].append(f"pagination_{name}: {err}")

test_pagination("fetch_events",
    lambda: pm.fetch_events(limit=3),
    lambda: pm.fetch_events(limit=10),
    lambda: pm.fetch_events(limit=3, offset=3))

test_pagination("fetch_series",
    lambda: pm.fetch_series(limit=3),
    lambda: pm.fetch_series(limit=10),
    lambda: pm.fetch_series(limit=3, offset=3))

test_pagination("fetch_tags",
    lambda: pm.fetch_tags(limit=3),
    lambda: pm.fetch_tags(limit=10),
    lambda: pm.fetch_tags(limit=3, offset=3))

test_pagination("fetch_public_trades",
    lambda: pm.fetch_public_trades(limit=3),
    lambda: pm.fetch_public_trades(limit=10),
    lambda: pm.fetch_public_trades(limit=3, offset=3))

test_pagination("search_markets",
    lambda: pm.search_markets(limit=3, query="bitcoin"),
    lambda: pm.search_markets(limit=10, query="bitcoin"),
    lambda: pm.search_markets(limit=3, offset=3, query="bitcoin"))

test_pagination("fetch_user_activity",
    lambda: pm.fetch_user_activity(TEST_ADDRESS, limit=3),
    lambda: pm.fetch_user_activity(TEST_ADDRESS, limit=10),
    lambda: pm.fetch_user_activity(TEST_ADDRESS, limit=3, offset=3))

test_pagination("fetch_closed_positions",
    lambda: pm.fetch_closed_positions(TEST_ADDRESS, limit=3),
    lambda: pm.fetch_closed_positions(TEST_ADDRESS, limit=10),
    lambda: pm.fetch_closed_positions(TEST_ADDRESS, limit=3, offset=3))

test_pagination("fetch_positions_data",
    lambda: pm.fetch_positions_data(TEST_ADDRESS, limit=3),
    lambda: pm.fetch_positions_data(TEST_ADDRESS, limit=10),
    lambda: pm.fetch_positions_data(TEST_ADDRESS, limit=3, offset=3))

test_pagination("fetch_leaderboard",
    lambda: pm.fetch_leaderboard(limit=5),
    lambda: pm.fetch_leaderboard(limit=25),
    lambda: pm.fetch_leaderboard(limit=5, offset=5))

test_pagination("fetch_builder_leaderboard",
    lambda: pm.fetch_builder_leaderboard(limit=3),
    lambda: pm.fetch_builder_leaderboard(limit=10),
    lambda: pm.fetch_builder_leaderboard(limit=3, offset=3))

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 60)
print("=== 전체 검증 결과 ===")
print(f"\n✅ 작동 ({len(results['ok'])}개):")
for r in results["ok"]:
    print(f"  - {r}")

print(f"\n⚠️ 부분 작동 ({len(results['partial'])}개):")
for r in results["partial"]:
    print(f"  - {r}")

print(f"\n❌ 실패 ({len(results['fail'])}개):")
for r in results["fail"]:
    print(f"  - {r}")

print(f"\n🔒 인증 필요 ({len(results['auth'])}개):")
for r in results["auth"]:
    print(f"  - {r}")
