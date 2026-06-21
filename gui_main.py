"""
GUI 入口。保留 main.py CLI 不变。
python gui_main.py  # 启动 GUI
python main.py      # 启动 CLI（不变）
"""
import sys
from novel_agent.gui.app import main

if __name__ == "__main__":
    sys.exit(main())
