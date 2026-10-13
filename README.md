# GenLayer Prediction Resolver

An **Intelligent Contract** on [GenLayer](https://genlayer.com) that turns the
open web into a prediction market oracle. Users register predictions and anyone
can resolve them once the deadline passes. Validators reach consensus on
**live web data and LLM judgements**, so no trusted oracle is involved.

> Deployed on **GenLayer Studionet** (chain id `61999`):
> **`0x8f64A7149c3121d355300927E46AC323E34D1d8b`**
> [View in the Studio explorer](https://explorer-studio.genlayer.com/address/0x8f64A7149c3121d355300927E46AC323E34D1d8b)

## What it does

Two kinds of predictions are supported:

| Kind | Example | How it is resolved |
|------|---------|--------------------|
| `price` | "bitcoin will be **above** $100,000 after 2026-12-31" | Fetches the spot price from the public CoinGecko API (`gl.nondet.web.get`). If the API fails or rate-limits, it renders the CoinGecko coin page and asks an LLM to pull out the price. |
| `event` | "Team A wins the 2026 final" + a resolution URL | Renders the URL (`gl.nondet.web.render`) and asks an LLM (`gl.nondet.exec_prompt`, JSON mode) for a `YES` / `NO` / `UNRESOLVED` verdict plus one sentence of evidence. |

### Consensus design (equivalence principle)

Both resolvers use `gl.vm.run_nondet_unsafe` with **custom validator functions**:

* **Price (outcome-equivalence, not just price tolerance):** every validator
  1. checks the leader is self-consistent (leader outcome == outcome of leader's price),
  2. fetches the price **itself**, computes **its own** `YES` / `NO` /
     `UNDETERMINED` outcome and requires it to be **strictly equal** to the
     leader's outcome,
  3. additionally requires the two prices to be within **1.5%** (plausibility).
* **Near-threshold dead zone:** if an observed price is within **1.5%** of the
  target, the outcome is `UNDETERMINED` and `resolve` reverts with
  *"price too close to target, retry later"*; the prediction stays open. Because
  the dead zone (1.5%) is >= the price tolerance, a decisive outcome can only be
  finalized when every agreeing node independently landed on the same side of
  the target with margin.
* **Event:** the validator re-runs the render + LLM pipeline and compares
  **only the verdict**. Different wording of the evidence is fine.
* If the leader errors, the validators disagree.
* `UNRESOLVED` (or a garbled LLM answer) reverts the transaction, so the
  prediction stays open and can be retried later.
* The prompts tell the model to treat page content as data and ignore any
  instructions in it (prompt-injection hardening).

### Security fix (v2): opposite outcomes can no longer both be approved

v1 validators only checked that the leader's price was within 1.5% of their own
and that the leader's outcome matched the *leader's* price. With a target of
$50,000, a leader seeing $50,100 (YES) and a validator seeing $49,900 (NO) are
only 0.4% apart, so the validator approved YES even though its own data said NO.
v2 fixes this with step 2 above (validator-derived outcome must equal the
leader's) plus the near-threshold dead zone. Regression tests:
`test_validator_rejects_opposite_outcome_within_tolerance`,
`test_near_threshold_is_undetermined`.

### On-chain state

* `predictions: DynArray[Prediction]`: full record of every prediction
  (creator, kind, parameters, deadline, status, outcome, observed evidence,
  resolver, timestamps)
* `user_index: TreeMap[Address, str]`: prediction ids per user
* `points / correct / wrong: TreeMap[Address, u256]`: per-user scoreboard
* `open_count / resolved_count / cancelled_count`: global counters

Deadlines are enforced against the transaction's block datetime
(`gl.message_raw["datetime"]`). Creators earn **1 point** whenever a prediction
resolves in their favour.

## Methods

### Write

| Method | Args | Description |
|--------|------|-------------|
| `create_price_prediction` | `asset_id: str` (CoinGecko id, e.g. `bitcoin`), `comparator: "above"\|"below"`, `target_price_usd: str` (e.g. `"100000.50"`; ints also accepted), `resolve_after: str` (ISO-8601, e.g. `2026-12-31T00:00:00Z`) | Registers a price prediction. Returns the id. |
| `create_event_prediction` | `question: str` (10-280 chars), `resolution_url: str` (https), `resolve_after: str`, `predicts_yes: bool` | Registers a yes/no event prediction. Returns the id. |
| `resolve` | `prediction_id: int` | Anyone can call this after `resolve_after`. Fetches web data, reaches consensus, stores the outcome, and updates scores. Returns `"YES"` / `"NO"`. |
| `cancel` | `prediction_id: int` | The creator can cancel an open prediction. |

### View

| Method | Returns |
|--------|---------|
| `get_prediction(prediction_id)` | One prediction as a dict |
| `get_predictions(offset, limit)` | A page of predictions (max 50) |
| `get_user_predictions(user)` | Prediction ids created by `user` |
| `get_user_stats(user)` | `{points, correct, wrong, created}` |
| `get_leaderboard(limit)` | `[{user, points}]` sorted by points |
| `get_stats()` | `{total, open, resolved, cancelled, owner}` |

## Live deployment (Studionet)

| | |
|---|---|
| Contract (v2, fixed) | [`0x9d703ef1DD55B1A0e350a7BF0c667ad6Bd7A6A87`](https://explorer-studio.genlayer.com/address/0x9d703ef1DD55B1A0e350a7BF0c667ad6Bd7A6A87) |
| Deploy tx (v2) | [`0xfdd46de0…bf0d`](https://explorer-studio.genlayer.com/tx/0xfdd46de003baf2518404b36c6c598ff990b7d019a3a41bd3e9fda98c8e95bf0d) |
| Previous v1 (superseded) | `0x8f64A7149c3121d355300927E46AC323E34D1d8b` |
| Network | Studionet, RPC `https://studio.genlayer.com/api`, chain id `61999` |

Demo transactions on the v2 contract (all `MAJORITY_AGREE`):

| Action | Tx | Result |
|--------|----|--------|
| `create_price_prediction(ethereum, below, 1000000, 2026-01-01T00:00:00Z)` | [`0x9577634c…04f5`](https://explorer-studio.genlayer.com/tx/0x9577634c8bd91e9c3948d94c7293203cb5b5ea25e50bcffabb675393d13b04f5) | id `1` |
| `resolve(1)`: validators derive their own outcome | [`0x4d3dcad9…ca9b`](https://explorer-studio.genlayer.com/tx/0x4d3dcad92707a115ed9bc058237d276ed3f1cf9ced9e7a568c820337900dca9b) | `YES`, `price_usd=2533.09` |

(id `0`, bitcoin above 1000, also resolved `YES`, `price_usd=84043.00`.)

Earlier demo transactions on the v1 contract:

| Action | Tx | Result |
|--------|----|--------|
| `create_event_prediction("Bitcoin's genesis block was mined in January 2009", https://en.wikipedia.org/wiki/Bitcoin, 2026-01-01T00:00:00Z, true)` | [`0x56dface4…6227`](https://explorer-studio.genlayer.com/tx/0x56dface4e46cba36f3ad8d409ad3c76c6c4565f984af6742c6a05aba60256227) | id `0` |
| `create_price_prediction(bitcoin, above, 1000, 2026-01-01T00:00:00Z)` | [`0x2e886d65…9791`](https://explorer-studio.genlayer.com/tx/0x2e886d654d7e1c4a577d6379245497d64adcc6357e1de2cfb9d56ec490aa9791) | id `1` |
| `resolve(0)`: web render + LLM verdict | [`0x824587a9…c10f`](https://explorer-studio.genlayer.com/tx/0x824587a9b461790694d1e75227f3dadd4658f04bb08011fbdc95c8024b94c10f) | `YES`, evidence: *"On 3 January 2009, the bitcoin network was created when Nakamoto mined the starting block of the chain, known as the genesis block."* |
| `resolve(1)`: CoinGecko price, tolerance consensus | [`0x651c6c76…dade`](https://explorer-studio.genlayer.com/tx/0x651c6c7677d44363de37292390ac30cdffe1b15573778d9cda6b4666ec8ddade) | `YES`, `price_usd=85646.00` |

Try it yourself:

```bash
genlayer network set studionet
C=0x9d703ef1DD55B1A0e350a7BF0c667ad6Bd7A6A87
genlayer call  $C get_stats
genlayer call  $C get_predictions --args 0 10
genlayer write $C create_price_prediction --args ethereum above 1000 2026-01-01T00:00:00Z
genlayer write $C resolve --args 2   # reverts if price is within 1.5% of target
genlayer call  $C get_leaderboard --args 10
```

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# lint (GenVM linter)
genvm-lint check contracts/prediction_resolver.py

# fast in-memory tests, with web + LLM mocked (18 tests)
pytest tests/direct/ -v
```

The direct-mode tests cover creation and input validation, price resolution
(including the LLM fallback when the API rate-limits), event resolution, the
`UNRESOLVED` revert, **validator behaviour** (own-outcome equality, near-threshold dead zone, tolerance band, a lying leader,
a leader error, verdict-only comparison via `run_validator`), deadline
enforcement, cancel permissions, pagination, and leaderboard ordering.

## Deploy

```bash
npm install -g genlayer
genlayer network set studionet         # or localnet / testnet-bradbury
genlayer account create --name deployer
# fund the account: on Studionet use the 💧 faucet in the Studio account selector
genlayer deploy --contract contracts/prediction_resolver.py
```

## Project layout

```
contracts/prediction_resolver.py    # the Intelligent Contract
tests/direct/                       # direct-mode tests (pytest + genlayer-test)
deploy/deployScript.ts              # optional scripted deploy (`genlayer deploy`)
.github/workflows/ci.yml            # lint + tests on every push
```

Built from the official
[genlayer-project-boilerplate](https://github.com/genlayerlabs/genlayer-project-boilerplate).
MIT licensed.
