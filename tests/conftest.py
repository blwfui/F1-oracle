"""pytest 配置：把仓库根目录放进 sys.path，让 `import src.xxx` 与 `import scripts.xxx` 可用。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "src" / "dashboard")):
    if p not in sys.path:
        sys.path.insert(0, p)
