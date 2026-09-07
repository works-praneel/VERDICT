"""Append-only JSON-lines logger for every agent decision in a run.

This log is the main way to *observe* the agent: each stage writes what it
decided and why, so a run can be replayed and narrated after the fact
(e.g. for the video walkthrough) without re-running anything.
"""
import json
import time
from pathlib import Path


class DecisionLogger:
    def __init__(self, path: str = "verdict_runs.jsonl"):
        self.path = Path(path)
        self.events = []

    def log(self, stage: str, data: dict):
        event = {"timestamp": time.time(), "stage": stage, **data}
        self.events.append(event)
        with self.path.open("a") as f:
            f.write(json.dumps(event) + "\n")

    def summary(self):
        return self.events
