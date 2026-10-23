"""pytest 公共配置：把仓库根目录加入 sys.path，使 `from src import ...` 可用。

★ 为什么需要：项目不是以包形式安装的（没有 setup.py / pyproject 的 package 配置），
  测试直接从仓库根目录导入模块，因此需要显式把根目录放进 sys.path。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
