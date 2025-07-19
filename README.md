# 2. 使用 uv 创建一个虚拟环境
# 这会在当前目录下创建一个 .venv 文件夹，类似于 python -m venv .venv
uv venv

# 3. 激活环境
# Windows (PowerShell):
# .\.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

# 确保你已在激活的环境中 (.venv)

uv pip sync pyproject.toml

# 1. 使用 uv pip install 安装核心库
# uv 的依赖解析和安装速度远超传统 pip
uv pip install jupyterlab pandas matplotlib scikit-learn ipykernel

# 2. (关键步骤) 将当前环境注册为 Jupyter 内核
# ipykernel 是连接你的代码和 Jupyter 前端的桥梁
python -m ipykernel install --user --name="my-data-analysis" --display-name="Python (My Data Analysis)"