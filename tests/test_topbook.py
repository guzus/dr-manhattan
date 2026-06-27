from decimal import Decimal

from dr_manhattan.marketdata import Level, Quote, TopBook, edge, edge_bps, levels, source_ts_ms


def test_levels_parse_common_shapes_and_sort():
    parsed_bids = levels(
        [
            {"price": "0.40", "size": "10"},
            ["0.42", "2.5"],
            {"price": "0", "size": "99"},
            {"price": "bad", "size": "1"},
        ],
        reverse=True,
    )
    parsed_asks = levels([("0.55", "1"), ("0.51", "3")], reverse=False)

    assert parsed_bids == [
        Level(Decimal("0.42"), Decimal("2.5")),
        Level(Decimal("0.40"), Decimal("10")),
    ]
    assert parsed_asks == [
        Level(Decimal("0.51"), Decimal("3")),
        Level(Decimal("0.55"), Decimal("1")),
    ]


def test_top_book_from_raw_exposes_best_prices_and_metadata():
    book = TopBook.from_raw(
        {
            "market": "condition-1",
            "asset_id": "token-1",
            "timestamp": "1782098035",
            "bids": [{"price": "0.48", "size": "12"}],
            "asks": [{"price": "0.50", "size": "2"}],
        }
    )

    assert book.market_id == "condition-1"
    assert book.asset_id == "token-1"
    assert book.source_ts_ms == 1782098035000
    assert book.best_bid == Decimal("0.48")
    assert book.best_ask == Decimal("0.50")
    assert book.bid_size == Decimal("12")
    assert book.ask_size == Decimal("2")
    assert book.mid_price == Decimal("0.49")
    assert book.fair == Decimal("0.49")
    assert book.spread == Decimal("0.02")
    assert book.ask.notional == Decimal("1.00")


def test_top_book_limits_depth_and_preserves_millisecond_timestamps():
    book = TopBook.from_raw(
        {
            "updateTimestampMs": "1782098035543",
            "bids": [("0.47", "1"), ("0.48", "1"), ("0.46", "1")],
            "asks": [("0.52", "1"), ("0.51", "1"), ("0.53", "1")],
        },
        depth=1,
    )

    assert book.source_ts_ms == 1782098035543
    assert book.bids == (Level(Decimal("0.48"), Decimal("1")),)
    assert book.asks == (Level(Decimal("0.51"), Decimal("1")),)


def test_quote_delegates_top_book_values():
    quote = Quote(
        venue="predictfun",
        market_id="pf-1",
        outcome="Yes",
        token_id="yes-token",
        key="match:2026-06-23:eng--gha:eng",
        question="Will England win?",
        observed_ms=1000,
        book=TopBook(
            bids=(Level(Decimal("0.48"), Decimal("10")),),
            asks=(Level(Decimal("0.50"), Decimal("5")),),
        ),
    )

    assert quote.bid == Decimal("0.48")
    assert quote.ask == Decimal("0.50")
    assert quote.bid_size == Decimal("10")
    assert quote.ask_size == Decimal("5")
    assert quote.fair == Decimal("0.49")


def test_edge_helpers_use_decimal_bps():
    assert edge(Decimal("0.53"), Decimal("0.50")) == Decimal("0.03")
    assert edge(Decimal("1"), Decimal("0.40"), Decimal("0.57")) == Decimal("0.03")
    assert edge(None, Decimal("0.50")) is None
    assert edge_bps(Decimal("0.0301")) == 301


def test_source_ts_ms_rejects_missing_and_invalid_values():
    assert source_ts_ms({}) is None
    assert source_ts_ms({"timestamp": "bad"}) is None
    assert source_ts_ms({"timestamp": "0"}) is None
    assert source_ts_ms({"timestamp": True}) is None
