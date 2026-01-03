# Cross-Exchange Module

Compare and match prediction markets across multiple exchanges.

## Structure

```
cross_exchange/
├── __init__.py      # Exports
├── types.py         # Data types (OutcomeMapping, FetchedMarkets, etc.)
├── manager.py       # CrossExchangeManager - fetches markets by mapping
└── matcher.py       # MarketMatcher - automatic market matching (skeleton)
```

## Type Hierarchy

```
OutcomeRef              # market_id + outcome (in models/market.py)
    └── OutcomeToken    # + token_id (extends OutcomeRef)

ExchangeOutcomeRef      # exchange_id + market_id + outcome (full reference)
```

## Design Choices

### 1. Manual Mapping (Current)

Users define explicit mappings between exchanges:

```python
OutcomeMapping = Dict[str, Dict[str, Dict[str, ExchangeOutcomeRef]]]
#                slug -> outcome_key -> exchange_id -> ref
```

**Pros:** Precise, no false matches, works immediately
**Cons:** Manual effort, doesn't scale

### 2. Automatic Matching (Skeleton)

Two planned approaches:

#### A. Category-Based Matching

Target specific market categories with known structures:

```
CategoryMatcher
├── FedDecisionMatcher     # Fed rate decisions (known outcome patterns)
├── ElectionMatcher        # Political elections (candidate-based)
├── CryptoHourlyMatcher    # Crypto price predictions (time-based)
└── SportsMatcher          # Sports events (team/player-based)
```

Each category has predictable outcome formats, making matching reliable.

**Pros:** High precision, predictable behavior
**Cons:** Limited to known categories

#### B. LLM-Based Matching (OpenRouter)

Use free models via OpenRouter for semantic matching:

```python
# Planned: LLMMatchStrategy
matcher = LLMMatchStrategy(
    provider="openrouter",
    model="meta-llama/llama-3-8b-instruct:free",
)
```

**Pros:** Handles arbitrary markets, understands context
**Cons:** API dependency, latency, rate limits

### 3. Exchange-Agnostic Design

All exchanges are treated equally - no "primary" exchange:

```python
MAPPING = {
    "fed-jan-2026": {
        "no-change": {
            POLYMARKET: ExchangeOutcomeRef(...),
            OPINION: ExchangeOutcomeRef(...),
        }
    }
}
```

## Usage

### Manual Mapping

```python
from dr_manhattan import (
    POLYMARKET,
    OPINION,
    CrossExchangeManager,
    ExchangeOutcomeRef,
    OutcomeMapping,
)

# Define mapping
MAPPING: OutcomeMapping = {
    "fed-jan-2026": {
        "no-change": {
            POLYMARKET: ExchangeOutcomeRef(POLYMARKET, "fed-decision-january", "Yes"),
            OPINION: ExchangeOutcomeRef(OPINION, "61", "450-475"),
        },
        "cut-25bps": {
            POLYMARKET: ExchangeOutcomeRef(POLYMARKET, "fed-decision-january", "No"),
            OPINION: ExchangeOutcomeRef(OPINION, "61", "425-450"),
        },
    },
}

# Fetch and compare
manager = CrossExchangeManager(MAPPING)
fetched = manager.fetch("fed-jan-2026")

# Get matched outcomes with prices
for match in fetched.get_matched_outcomes():
    print(f"{match.outcome_key}: spread={match.spread:.4f}")
    for ex_id, price in match.prices.items():
        print(f"  {ex_id}: {price.price}")
```

### Automatic Matching (When Implemented)

#### Category-Based

```python
from dr_manhattan.cross_exchange import (
    MarketMatcher,
    FedDecisionMatcher,
)

# Category-specific matcher
matcher = MarketMatcher(
    strategies=[FedDecisionMatcher()],
)

# Find Fed decision markets across exchanges
candidates = matcher.find_matches(
    source_markets=polymarket_markets,
    target_markets=opinion_markets,
    source_exchange="polymarket",
    target_exchange="opinion",
    threshold=0.8,
)
```

#### LLM-Based (OpenRouter)

```python
from dr_manhattan.cross_exchange import (
    MarketMatcher,
    LLMMatchStrategy,
)

# LLM-powered matching via OpenRouter free models
matcher = MarketMatcher(
    strategies=[
        LLMMatchStrategy(
            provider="openrouter",
            model="meta-llama/llama-3-8b-instruct:free",
        )
    ],
)

# Find semantically similar markets
candidates = matcher.find_matches(
    source_markets=polymarket_markets,
    target_markets=opinion_markets,
    source_exchange="polymarket",
    target_exchange="opinion",
    threshold=0.7,
)

for c in candidates:
    print(f"Score: {c.score:.2f} | {c.market_a.market_id} <-> {c.market_b.market_id}")
```

## Data Flow

```
1. User defines OutcomeMapping
       │
       v
2. CrossExchangeManager.fetch(slug)
       │
       ├── Fetches markets from each exchange
       │
       v
3. FetchedMarkets
       │
       ├── markets: Dict[exchange_id, List[Market]]
       ├── outcome_mapping: reference to original mapping
       │
       v
4. FetchedMarkets.get_matched_outcomes()
       │
       ├── Aligns outcomes using mapping
       ├── Extracts prices from markets
       │
       v
5. List[MatchedOutcome]
       │
       ├── outcome_key: "no-change"
       ├── prices: {polymarket: TokenPrice, opinion: TokenPrice}
       └── spread: price difference
```

## Future Considerations

1. **Category Matchers**: Implement matchers for Fed, elections, crypto, sports
2. **OpenRouter Integration**: LLM matching with free models (llama-3, mistral)
3. **Outcome Alignment**: Map "Yes/No" to multi-outcome markets via LLM
4. **Caching**: Cache market data and LLM responses to reduce API calls
5. **Hybrid Approach**: Category matcher first, LLM fallback for unknown types
