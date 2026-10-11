"""Compare ordered retrieval, construction time, and Python allocations; no LLM."""
from __future__ import annotations

import argparse
import gc
import json
import platform
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
import tracemalloc

# Support direct invocation from an uninstalled repository checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from socioverse.engine.messaging import InMemoryMessageBus
from socioverse.optimizations.indexed_messaging import IndexedMessageBus


def build(bus_type, history, degree):
    bus = bus_type()
    for i in range(history):
        bus.post({"author_id": f"old-{i % 100}", "step": i % 98,
                  "round": 0, "content": str(i)})
    for i in range(degree):
        for step, round_idx in ((99, 0), (100, 1), (100, 3)):
            bus.post({"author_id": f"peer-{i}", "step": step,
                      "round": round_idx, "content": f"{i}:{step}:{round_idx}"})
    return bus


def measure(history, degree, repeats, queries):
    buses, construction = {}, {}
    for name, bus_type in (("scan", InMemoryMessageBus), ("indexed", IndexedMessageBus)):
        start = perf_counter()
        buses[name] = build(bus_type, history, degree)
        construction[name] = perf_counter() - start
    neighbors = [f"peer-{i}" for i in range(degree)]
    expected = buses["scan"].visible_to("recipient", neighbors, 100, 2)
    actual = buses["indexed"].visible_to("recipient", neighbors, 100, 2)
    if actual != expected or len(actual) != 2 * degree:
        raise AssertionError("Ordered visibility differs from reference")
    timings = {name: [] for name in buses}
    # Alternate measurement order to reduce fixed-order timing bias.
    for repeat in range(repeats):
        order = ("scan", "indexed") if repeat % 2 == 0 else ("indexed", "scan")
        for name in order:
            start = perf_counter()
            for _ in range(queries):
                buses[name].visible_to("recipient", neighbors, 100, 2)
            timings[name].append((perf_counter() - start) / queries)
    latency = {name: median(samples) for name, samples in timings.items()}
    return {"unrelated_history": history, "neighbors": degree,
            "messages": history + 3 * degree, "visible": len(actual),
            "indexed_candidates": buses["indexed"].last_candidates,
            "ordered_equal": True, "retrieval_seconds": latency,
            "retrieval_speedup": latency["scan"] / latency["indexed"],
            "construction_and_posting_seconds": construction}


def memory(bus_type):
    gc.collect()
    tracemalloc.start()
    try:
        bus = build(bus_type, 10000, 16)
        current, peak = tracemalloc.get_traced_memory()
        if len(bus.visible_to("recipient", [f"peer-{i}" for i in range(16)], 100, 2)) != 32:
            raise AssertionError("Unexpected memory benchmark feed")
        return {"messages": 10048, "python_traced_current_bytes": current,
                "python_traced_peak_bytes": peak}
    finally:
        tracemalloc.stop()


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=positive, nargs="+", default=[1000, 10000, 100000])
    parser.add_argument("--degree", type=positive, nargs="+", default=[4, 16, 64])
    parser.add_argument("--repeats", type=positive, default=5)
    parser.add_argument("--queries", type=positive, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("output already exists; choose a new path")
    result = {"scope": "Synthetic communication benchmark; no LLM or end-to-end speedup claim.",
              "python": sys.version, "platform": platform.platform(),
              "repeats": args.repeats, "queries_per_repeat": args.queries,
              "cells": [measure(h, d, args.repeats, args.queries)
                        for h in args.history for d in args.degree],
              "memory": {"scan": memory(InMemoryMessageBus),
                         "indexed": memory(IndexedMessageBus)},
              "memory_note": "Python allocations only; not process resident memory."}
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    print(encoded, end="")


if __name__ == "__main__":
    main()
