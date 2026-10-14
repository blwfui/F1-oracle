# F1 Oracle — 启动仪表板
#
# ⚠️ PYTHONPATH 必须包含 src/，这不是可有可无的：
#    Streamlit 的文件监听器用 file_in_pythonpath() 判断一个模块是否该被监听，
#    而那个函数读的是 **PYTHONPATH 环境变量**（不是 sys.path）。
#    src/ 不在 PYTHONPATH 里 → src/model/*.py 永远不会被监听 → 改动后页面
#    只重载 src/dashboard/ 下的文件、模型层却还是旧代码，
#    于是报出「代码明明改对了，运行时报旧签名/旧行为」这类假 bug
#    （例如 LapTimeline.convergence() takes 1 positional argument but 2 were given）。
#
#    只加 src（不加仓库根目录），是为了避免把 .venv/ 也拖进监听范围。
param([int]$Port = 8517)

Set-Location $PSScriptRoot

$env:PYTHONPATH = "$PSScriptRoot\src"

. "$PSScriptRoot\.venv\Scripts\Activate.ps1"

# 用 python -m 启动：把仓库根目录（cwd）放进 sys.path[0]，
# 页面里的 `from src.model.xxx import ...` 才解析得到。
python -m streamlit run src/dashboard/app.py --server.port $Port
