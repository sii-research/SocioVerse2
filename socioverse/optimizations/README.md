# Indexed message bus

`IndexedMessageBus` is an opt-in implementation of the existing `MessageBus`
interface. It accelerates neighborhood message retrieval without changing the
default `InMemoryMessageBus` or the simulation engine.

## Use with NeighborFeed

```python
from socioverse.env_layers.neighbor_feed import NeighborFeed
from socioverse.optimizations.indexed_messaging import IndexedMessageBus
from socioverse.schemas.runtime import Action

network = {"alice": ["bob"], "bob": ["alice"]}
bus = IndexedMessageBus(carry_previous_step=True)
feed = NeighborFeed(neighbors_fn=lambda agent_id: network[agent_id], bus=bus)
feed.ingest([
    Action(step=2, agent_id="bob", kind="post", payload={"content": "Hello Alice"}),
], step=2, round_idx=0)

assert feed.local_for("alice", t=2, round_idx=0) == {}
assert feed.local_for("alice", t=2, round_idx=1) == {
    "feed": [{"from": "bob", "content": "Hello Alice"}]
}
```

The environment provider owns the bus. Pass it to that provider's `NeighborFeed`
or use `post`, `visible_to`, `fetch`, and `drain` directly. Existing studies must
explicitly adopt it; providers with their own feed logic are not automatically
accelerated. No LLM configuration changes are required.

## How retrieval works

The reference bus scans its complete message history for every query. This bus
also retains complete history, but maintains buckets keyed by `(step, author_id)`.
A query reads the requested neighbors' current-step buckets and, when enabled,
their previous-step buckets. It filters rounds and sorts by posting sequence.

The result preserves the reference bus's semantics:

- Only neighbors' messages are visible; duplicate neighbors do not duplicate messages.
- Current-step messages require `message.round < round_idx`.
- With `carry_previous_step=True`, all previous-step rounds are eligible.
- Results retain global posting order, even when authors and steps are interleaved.
- `fetch` uses round zero. Missing `round` and `channel` default to `0` and `"chat"`.
- `drain` clears the pending persistence buffer, not retained history.
- Historical queries remain supported; there is no history eviction.

For `d` distinct neighbors, `c` bucket candidates, and `v` visible messages,
normal retrieval costs `O(d + c + v log v)`, versus the reference scan's
`O(d + M)` for `M` retained messages. Posting maintains an additional index and
storage remains `O(M)` with extra references and tracking objects. Dense
neighborhoods or many messages in eligible buckets can limit the benefit.

Returned messages are mutable dictionary subclasses. Normal mapping mutations
invalidate the index, which is rebuilt lazily on the next query (`O(M)`).
Unhashable routing fields fall back to reference scanning, including the
reference implementation's validation/error behavior. Mutating private history
or bypassing subclass methods with calls such as `dict.__setitem__` is unsupported.
Both buses are single-threaded and require external synchronization for concurrent use.

## Validate and benchmark

From the repository root, using the environment where SocioVerse2 is installed:

```sh
python -m pytest tests/test_indexed_messaging.py -q
python scripts/benchmark_indexed_messaging.py --history 1000 10000 100000 --degree 4 16 64
```

The tests compare ordered results against the reference implementation across
random operations, historical queries, both carry modes, mutations, draining,
and `NeighborFeed` integration. The benchmark checks ordered equality before
timing, then reports median retrieval latency, construction/posting time, and
Python-traced allocations. It prints JSON, requires no model, API key, or network,
and accepts `--output PATH` to save a new result file (existing files are refused).

The benchmark deliberately separates unrelated history from local messages to
expose retrieval scaling. Timings depend on hardware and workload; construction
includes message creation as well as posting, and traced allocation figures are
not process resident memory. Compare posting and memory costs alongside lookup
speed. These measurements do not establish end-to-end simulation speedup.

Equal ordered feeds preserve communication inputs for the same posted messages.
This optimization does not reduce LLM calls, tokens, or stochastic model variation.
Identical final trajectories additionally require identical actions and other
simulation inputs; independent LLM runs need not reproduce each other.
