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

* **Price:** the validator checks that the leader's outcome matches the leader's
  own price. It then fetches the price itself and accepts if the two prices are
  within **1.5%** of each other. A tolerance band is needed because prices move
  between nodes, so exact equality would never reach agreement.
* **Event:** the validator re-runs the render + LLM pipeline and compares
  **only the verdict**. Different wording of the evidence is fine.
* If the leader errors, the validators disagree.
* `UNRESOLVED` (or a garbled LLM answer) reverts the transaction, so the
  prediction stays open and can be retried later.
* The prompts tell the model to treat page content as data and ignore any
  instructions in it (prompt-injection hardening).

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
| Contract | [`0x8f64A7149c3121d355300927E46AC323E34D1d8b`](https://explorer-studio.genlayer.com/address/0x8f64A7149c3121d355300927E46AC323E34D1d8b) |
| Deploy tx | [`0x3bdcd21def637f12ab4b14b7b16d9e01bbd04203b15c9be5f20393ba0c5e34e5`](https://explorer-studio.genlayer.com/tx/0x3bdcd21def637f12ab4b14b7b16d9e01bbd04203b15c9be5f20393ba0c5e34e5) (FINALIZED, MAJORITY_AGREE) |
| Network | Studionet, RPC `https://studio.genlayer.com/api`, chain id `61999` |

Demo transactions on the live contract (all `MAJORITY_AGREE`):

| Action | Tx | Result |
|--------|----|--------|
| `create_event_prediction("Bitcoin's genesis block was mined in January 2009", https://en.wikipedia.org/wiki/Bitcoin, 2026-01-01T00:00:00Z, true)` | [`0x56dface4…6227`](https://explorer-studio.genlayer.com/tx/0x56dface4e46cba36f3ad8d409ad3c76c6c4565f984af6742c6a05aba60256227) | id `0` |
| `create_price_prediction(bitcoin, above, 1000, 2026-01-01T00:00:00Z)` | [`0x2e886d65…9791`](https://explorer-studio.genlayer.com/tx/0x2e886d654d7e1c4a577d6379245497d64adcc6357e1de2cfb9d56ec490aa9791) | id `1` |
| `resolve(0)`: web render + LLM verdict | [`0x824587a9…c10f`](https://explorer-studio.genlayer.com/tx/0x824587a9b461790694d1e75227f3dadd4658f04bb08011fbdc95c8024b94c10f) | `YES`, evidence: *"On 3 January 2009, the bitcoin network was created when Nakamoto mined the starting block of the chain, known as the genesis block."* |
| `resolve(1)`: CoinGecko price, tolerance consensus | [`0x651c6c76…dade`](https://explorer-studio.genlayer.com/tx/0x651c6c7677d44363de37292390ac30cdffe1b15573778d9cda6b4666ec8ddade) | `YES`, `price_usd=85646.00` |

Try it yourself:

```bash
genlayer network set studionet
C=0x8f64A7149c3121d355300927E46AC323E34D1d8b
genlayer call  $C get_stats
genlayer call  $C get_predictions --args 0 10
genlayer write $C create_price_prediction --args ethereum above 1000 2026-01-01T00:00:00Z
genlayer write $C resolve --args 2
genlayer call  $C get_leaderboard --args 10
```

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# lint (GenVM linter)
genvm-lint check contracts/prediction_resolver.py

# fast in-memory tests, with web + LLM mocked (16 tests)
pytest tests/direct/ -v
```

The direct-mode tests cover creation and input validation, price resolution
(including the LLM fallback when the API rate-limits), event resolution, the
`UNRESOLVED` revert, **validator behaviour** (tolerance band, a lying leader,
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
