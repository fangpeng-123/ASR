import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


@dataclass
class AppConfig:
    host: str
    port: int
    default_model: str
    formats: List[str]
    sample_rates: List[int]
    supported_combinations: List[Tuple[str, int]]
    frame_ms: int

    def is_supported(self, model: str, format: str, sample_rate: int) -> bool:
        if format not in self.formats:
            return False
        if sample_rate not in self.sample_rates:
            return False
        return (model, sample_rate) in self.supported_combinations


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    combos = [(c[0], int(c[1])) for c in raw["asr"]["supported_combinations"]]
    return AppConfig(
        host=raw["server"]["host"],
        port=int(raw["server"]["port"]),
        default_model=raw["dashscope"]["default_model"],
        formats=list(raw["asr"]["formats"]),
        sample_rates=list(raw["asr"]["sample_rates"]),
        supported_combinations=combos,
        frame_ms=int(raw["asr"]["frame_ms"]),
    )


def get_api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        raise RuntimeError("DASHSCOPE_API_KEY environment variable not set")
    return key
