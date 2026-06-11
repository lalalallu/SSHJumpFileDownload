#!/usr/bin/env python3
"""
SSH跳板机文件下载器 - 主程序入口
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from ui.main_window import MainWindow


def main():
    """主函数"""
    # 创建应用
    app = QApplication(sys.argv)
    app.setApplicationName("SSH跳板机文件下载器")
    app.setApplicationVersion("1.0.0")
    
    # 设置样式
    app.setStyle("Fusion")
    
    # 创建主窗口
    window = MainWindow()
    window.show()
    
    # 运行应用
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
