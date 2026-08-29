from __future__ import annotations

import os
from pathlib import Path

CACHE_DIR = Path(os.environ.get("MODEL_EVAL_CACHE_DIR", Path.cwd() / ".model_cache"))
