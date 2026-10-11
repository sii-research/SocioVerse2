from __future__ import annotations

import random

import pytest

from socioverse.engine.messaging import InMemoryMessageBus
from socioverse.optimizations.indexed_messaging import IndexedMessageBus


@pytest.mark.parametrize('carry', [False, True])
def test_random_operation_sequences_match_ordered_reference(carry):
    rng = random.Random(42)
    baseline, indexed = InMemoryMessageBus(carry), IndexedMessageBus(carry)
    for i in range(600):
        if rng.random() < 0.6:
            message = {'author_id': rng.choice(['a', 'b', 'c']),
                       'step': rng.randrange(10), 'content': str(i)}
            if rng.random() < 0.7:
                message['round'] = rng.randrange(4)
            baseline.post(message)
            indexed.post(message)
        else:
            neighbors = rng.choices(['a', 'b', 'c', 'absent'], k=rng.randrange(6))
            step, round_idx = rng.randrange(12), rng.randrange(5)
            assert indexed.visible_to('x', neighbors, step, round_idx) == baseline.visible_to(
                'x', neighbors, step, round_idx)
            assert indexed.fetch('x', step, neighbors) == baseline.fetch('x', step, neighbors)
        if rng.random() < 0.15:
            assert indexed.drain() == baseline.drain()
    assert indexed.drain() == baseline.drain()
    assert indexed.drain() == []


def test_interleaved_order_and_unrelated_history():
    baseline, indexed = InMemoryMessageBus(), IndexedMessageBus()
    for i in range(1000):
        message = {'author_id': 'irrelevant', 'step': i, 'content': 'old'}
        baseline.post(message)
        indexed.post(message)
    for author, step, rnd in [('b', 5, 1), ('a', 4, 99), ('a', 5, 0), ('b', 5, 2)]:
        message = {'author_id': author, 'step': step, 'round': rnd}
        baseline.post(message)
        indexed.post(message)
    assert indexed.visible_to('x', ['a', 'b', 'a'], 5, 2) == baseline.visible_to(
        'x', ['a', 'b', 'a'], 5, 2)
    assert indexed.last_candidates == 4
    assert len(indexed.visible_to('x', ['a', 'b'], 5, 2)) == 3


@pytest.mark.parametrize('mutate', [
    lambda m: m.update(step=8, author_id='b'),
    lambda m: m.__setitem__('step', 8),
    lambda m: m.pop('author_id'),
    lambda m: m.clear(),
])
def test_returned_mapping_mutation_remains_visible(mutate):
    baseline, indexed = InMemoryMessageBus(), IndexedMessageBus()
    for bus in (baseline, indexed):
        bus.post({'author_id': 'a', 'step': 2})
        mutate(bus.drain()[0])
    for step in (2, 3, 8, 9):
        assert indexed.visible_to('x', ['a', 'b'], step, 1) == baseline.visible_to(
            'x', ['a', 'b'], step, 1)


@pytest.mark.parametrize('mutate', [
    lambda m: m.__delitem__('author_id'),
    lambda m: m.popitem(),
    lambda m: (m.pop('step'), m.setdefault('step', 8)),
    lambda m: m.__ior__({'step': 8, 'author_id': 'b'}),
])
def test_additional_mapping_mutations_rebuild_index(mutate):
    baseline, indexed = InMemoryMessageBus(), IndexedMessageBus()
    for bus in (baseline, indexed):
        bus.post({'author_id': 'a', 'step': 2, 'content': 'hello'})
        mutate(bus.visible_to('x', ['a'], 2, 1)[0])
    for step in (2, 3, 8, 9):
        assert indexed.visible_to('x', ['a', 'b'], step, 1) == baseline.visible_to(
            'x', ['a', 'b'], step, 1)


def test_partial_update_failure_invalidates_index():
    baseline, indexed = InMemoryMessageBus(), IndexedMessageBus()
    for bus in (baseline, indexed):
        bus.post({'author_id': 'a', 'step': 2})
        message = bus.visible_to('x', ['a'], 2, 1)[0]
        with pytest.raises(ValueError):
            message.update([('step', 8), ('invalid',)])
    assert indexed.visible_to('x', ['a'], 8, 1) == baseline.visible_to('x', ['a'], 8, 1)


def test_unhashable_step_falls_back_to_reference_scan():
    baseline, indexed = InMemoryMessageBus(), IndexedMessageBus()
    for bus in (baseline, indexed):
        bus.post({'author_id': 'a', 'step': [2]})
        bus.post({'author_id': 'a', 'step': 2, 'content': 'valid'})
    assert indexed.visible_to('x', ['a'], 2, 1) == baseline.visible_to('x', ['a'], 2, 1)
    assert indexed.last_candidates == 2


def test_unhashable_author_preserves_reference_error():
    for bus in (InMemoryMessageBus(), IndexedMessageBus()):
        bus.post({'author_id': ['a'], 'step': 2})
        with pytest.raises(TypeError):
            bus.visible_to('x', ['a'], 2, 1)


def test_input_copy_defaults_and_drain_retained_history():
    for bus in (InMemoryMessageBus(), IndexedMessageBus()):
        original = {'author_id': 'a', 'step': 2}
        bus.post(original)
        original['step'] = 99
        assert bus.fetch('x', 2, ['a']) == []
        expected = [{'author_id': 'a', 'step': 2, 'round': 0, 'channel': 'chat'}]
        assert bus.drain() == expected
        assert bus.drain() == []
        assert bus.fetch('x', 3, ['a']) == expected
        assert bus.visible_to('x', ['a'], 2, 1) == expected


def test_neighbor_feed_rounds_and_previous_step_match_reference():
    from socioverse.env_layers.neighbor_feed import NeighborFeed
    from socioverse.schemas.runtime import Action

    neighbors = {'alice': ['bob', 'bob'], 'bob': ['alice']}
    feeds = [NeighborFeed(lambda agent_id: neighbors[agent_id], bus=bus)
             for bus in (InMemoryMessageBus(), IndexedMessageBus())]
    actions = [Action(step=2, agent_id='bob', kind='post', payload={'content': 'Hello Alice'}),
               Action(step=2, agent_id='outsider', kind='reply', payload={'content': 'Hidden'}),
               Action(step=2, agent_id='bob', kind='wait', payload={})]
    assert feeds[0].ingest(actions, 2, 0) == feeds[1].ingest(actions, 2, 0)
    assert feeds[0].local_for('alice', 2, 0) == feeds[1].local_for('alice', 2, 0) == {}
    expected = {'feed': [{'from': 'bob', 'content': 'Hello Alice'}]}
    for step, round_idx in ((2, 1), (3, 0)):
        assert feeds[0].local_for('alice', step, round_idx) == expected
        assert feeds[1].local_for('alice', step, round_idx) == expected
    assert feeds[0].local_for('alice', 4, 0) == feeds[1].local_for('alice', 4, 0) == {}
