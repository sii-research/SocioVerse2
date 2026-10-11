"""Neighborhood-local retrieval preserving the reference bus's posting order."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from socioverse.engine.messaging import InMemoryMessageBus


class _TrackedMessage(dict):
    """Invalidate routing indexes if a caller mutates a returned message."""
    def __init__(self, message, changed):
        super().__init__(message)
        self.changed = changed

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.changed()

    def __delitem__(self, key):
        super().__delitem__(key)
        self.changed()

    def update(self, *args, **kwargs):
        try:
            super().update(*args, **kwargs)
        finally:
            self.changed()

    def setdefault(self, key, default=None):
        if key not in self:
            self.changed()
        return super().setdefault(key, default)

    def pop(self, *args):
        result = super().pop(*args)
        self.changed()
        return result

    def popitem(self):
        result = super().popitem()
        self.changed()
        return result

    def clear(self):
        super().clear()
        self.changed()

    def __ior__(self, other):
        self.update(other)
        return self


class IndexedMessageBus(InMemoryMessageBus):
    """Index (step, author) buckets; keep history and drain semantics unchanged.

    Retrieval inspects only neighboring authors in the two eligible steps, then
    sorts by insertion sequence. Cost: O(d + c + v log v), for d unique neighbors,
    c candidates, v visible messages. No eviction, including for historical queries.
    Mutations through returned message mappings trigger a lazy index rebuild.
    Non-hashable routing fields fall back to the reference scan. As with the
    reference bus, this class is not thread-safe.
    """
    def __init__(self, carry_previous_step: bool = True) -> None:
        super().__init__(carry_previous_step)
        self._index = defaultdict(list)
        self._dirty = False
        self._unindexable = False
        self.last_candidates = 0

    def _invalidate(self):
        self._dirty = True

    def _index_message(self, sequence, message):
        try:
            self._index[(message.get('step'), message.get('author_id'))].append((sequence, message))
        except TypeError:
            self._unindexable = True

    def post(self, message: dict[str, Any]) -> None:
        msg = dict(message)
        msg.setdefault('round', 0)
        msg.setdefault('channel', 'chat')
        tracked = _TrackedMessage(msg, self._invalidate)
        sequence = len(self._messages)
        self._messages.append(tracked)
        self._round_buffer.append(tracked)
        self._index_message(sequence, tracked)

    def visible_to(self, recipient_id: str, neighbors: list[str], step: int,
                   round_idx: int = 0) -> list[dict[str, Any]]:
        if self._dirty:
            self._index.clear()
            self._unindexable = False
            for sequence, message in enumerate(self._messages):
                self._index_message(sequence, message)
            self._dirty = False
        if self._unindexable:
            self.last_candidates = len(self._messages)
            return super().visible_to(recipient_id, neighbors, step, round_idx)
        candidates = []
        for author in set(neighbors):
            candidates.extend(self._index.get((step, author), ()))
            if self.carry_previous_step:
                candidates.extend(self._index.get((step - 1, author), ()))
        self.last_candidates = len(candidates)
        visible = [(sequence, m) for sequence, m in candidates
                   if (m.get('step') == step and m.get('round', 0) < round_idx)
                   or (self.carry_previous_step and m.get('step') == step - 1)]
        visible.sort(key=lambda pair: pair[0])
        return [message for _, message in visible]
