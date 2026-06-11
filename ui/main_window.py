"""
主窗口 - SSH跳板机文件下载器主界面
"""
import os
import threading
from datetime import datetime
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QSplitter, QScrollArea,
    QFileDialog, QMessageBox, QStatusBar, QToolBar, QMenu, QMenuBar
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon

from models.server import JumpChain
from models.download_task import DownloadTask, DownloadStatus
from core.connection import SSHConnectionManager
from core.sftp_client import SFTPClientWrapper
from core.downloader import DownloadManager
from ui.dialogs.connection_dialog import ConnectionDialog
from ui.widgets.file_list_widget import FileListWidget
from ui.widgets.download_item_widget import DownloadItemWidget
from ui.widgets.server_info_widget import ServerInfoWidget
from core.sftp_client import RemoteFile


class MainWindow(QMainWindow):
    """主窗口"""
    
    # 后台目录加载完成信号
    files_loaded = pyqtSignal(object, object)  # (files, error)
    
    def __init__(self):
        super().__init__()
        
        # 核心组件
        self._connection = None
        self._sftp = None
        self._downloader = None
        self._jump_chain = None
        
        # 当前路径
        self._current_path = "/"
        
        # 下载项组件缓存
        self._download_widgets = {}
        
        # 后台加载线程
        self._loading_thread = None
        
        # 设置界面
        self._setup_ui()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_statusbar()
        self._connect_signals()
        
        # 进度更新定时器
        self._update_timer = QTimer()
        self._update_timer.timeout.connect(self._update_progress)
        self._update_timer.start(500)  # 每500ms更新一次
        
        # 连接信号
        self.files_loaded.connect(self._on_directory_loaded)
    
    def _setup_ui(self):
        """设置界面"""
        self.setWindowTitle("SSH跳板机文件下载器")
        self.setGeometry(100, 100, 1200, 800)
        
        # 中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        
        # 创建分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        
        # 左侧面板 - 服务器信息
        self.server_info_widget = ServerInfoWidget()
        splitter.addWidget(self.server_info_widget)
        
        # 中间面板 - 文件列表
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        
        # 路径栏
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("远程目录:"))
        
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("输入路径...")
        self.path_edit.returnPressed.connect(self._navigate_to_path)
        path_layout.addWidget(self.path_edit)
        
        self.browse_btn = QPushButton("浏览")
        self.browse_btn.clicked.connect(self._browse_home)
        path_layout.addWidget(self.browse_btn)
        
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self._refresh_file_list)
        path_layout.addWidget(self.refresh_btn)
        
        center_layout.addLayout(path_layout)
        
        # 文件列表
        self.file_list = FileListWidget()
        center_layout.addWidget(self.file_list)
        
        splitter.addWidget(center_widget)
        
        # 右侧面板 - 已选文件和下载
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # 已选文件区域
        selected_group = QWidget()
        selected_layout = QVBoxLayout(selected_group)
        
        selected_header = QHBoxLayout()
        self.selected_count_label = QLabel("已选文件 (0项, 共 0 B)")
        selected_header.addWidget(self.selected_count_label)
        
        self.clear_selection_btn = QPushButton("清空")
        self.clear_selection_btn.clicked.connect(self._clear_selection)
        selected_header.addWidget(self.clear_selection_btn)
        
        self.download_btn = QPushButton("下载选中")
        self.download_btn.clicked.connect(self._start_download)
        self.download_btn.setEnabled(False)
        selected_header.addWidget(self.download_btn)
        
        selected_layout.addLayout(selected_header)
        
        # 已选文件列表
        self.selected_list_label = QLabel("无选中文件")
        self.selected_list_label.setStyleSheet("color: #6c757d; padding: 8px;")
        selected_layout.addWidget(self.selected_list_label)
        
        # 本地保存路径
        local_path_layout = QHBoxLayout()
        local_path_layout.addWidget(QLabel("保存到:"))
        
        self.local_path_edit = QLineEdit()
        self.local_path_edit.setText(os.path.expanduser("~/Downloads"))
        local_path_layout.addWidget(self.local_path_edit)
        
        self.browse_local_btn = QPushButton("浏览...")
        self.browse_local_btn.clicked.connect(self._browse_local_path)
        local_path_layout.addWidget(self.browse_local_btn)
        
        selected_layout.addLayout(local_path_layout)
        right_layout.addWidget(selected_group)
        
        # 下载进度区域
        progress_group = QWidget()
        progress_layout = QVBoxLayout(progress_group)
        
        progress_header_layout = QHBoxLayout()
        progress_header = QLabel("下载进度")
        progress_header.setStyleSheet("font-weight: bold;")
        progress_header_layout.addWidget(progress_header)
        
        # 清空已完成按钮
        self.clear_completed_btn = QPushButton("清空已完成")
        self.clear_completed_btn.setFixedWidth(100)
        self.clear_completed_btn.clicked.connect(self._clear_completed_downloads)
        progress_header_layout.addWidget(self.clear_completed_btn)
        
        progress_layout.addLayout(progress_header_layout)
        
        # 下载项滚动区域
        self.download_scroll = QScrollArea()
        self.download_scroll.setWidgetResizable(True)
        self.download_scroll.setStyleSheet("QScrollArea { border: none; }")
        
        self.download_container = QWidget()
        self.download_container_layout = QVBoxLayout(self.download_container)
        self.download_container_layout.addStretch()
        
        self.download_scroll.setWidget(self.download_container)
        progress_layout.addWidget(self.download_scroll)
        
        # 总进度
        self.total_progress_label = QLabel("总进度: 0%")
        progress_layout.addWidget(self.total_progress_label)
        
        right_layout.addWidget(progress_group)
        
        splitter.addWidget(right_widget)
        
        # 设置分割器比例
        splitter.setSizes([200, 600, 400])
    
    def _setup_menu(self):
        """设置菜单"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")
        
        connect_action = QAction("新建连接(&N)", self)
        connect_action.setShortcut("Ctrl+N")
        connect_action.triggered.connect(self._show_connection_dialog)
        file_menu.addAction(connect_action)
        
        disconnect_action = QAction("断开连接(&D)", self)
        disconnect_action.triggered.connect(self._disconnect)
        file_menu.addAction(disconnect_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("退出(&X)", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 设置菜单
        settings_menu = menubar.addMenu("设置(&S)")
        
        preferences_action = QAction("首选项(&P)", self)
        settings_menu.addAction(preferences_action)
        
        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")
        
        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
    
    def _setup_toolbar(self):
        """设置工具栏"""
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        connect_btn = QPushButton("连接")
        connect_btn.clicked.connect(self._show_connection_dialog)
        toolbar.addWidget(connect_btn)
        
        disconnect_btn = QPushButton("断开")
        disconnect_btn.clicked.connect(self._disconnect)
        toolbar.addWidget(disconnect_btn)
        
        toolbar.addSeparator()
        
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._refresh_file_list)
        toolbar.addWidget(refresh_btn)
    
    def _setup_statusbar(self):
        """设置状态栏"""
        self.statusBar().showMessage("就绪")
    
    def _connect_signals(self):
        """连接信号"""
        # 服务器信息组件
        self.server_info_widget.disconnect_clicked.connect(self._disconnect)
        
        # 文件列表组件
        self.file_list.selection_changed.connect(self._on_selection_changed)
        self.file_list.file_double_clicked.connect(self._on_file_double_click)
        self.file_list.refresh_btn.clicked.connect(self._refresh_file_list)
    
    def _show_connection_dialog(self):
        """显示连接对话框"""
        dialog = ConnectionDialog(self)
        dialog.connection_established.connect(self._on_connection_established)
        dialog.exec()
    
    def _on_connection_established(self, jump_chain: JumpChain):
        """连接建立成功"""
        try:
            # 创建连接
            self._connection = SSHConnectionManager()
            self._connection.connect(jump_chain)
            
            # 创建SFTP客户端
            self._sftp = SFTPClientWrapper(self._connection)
            
            # 创建下载管理器
            self._downloader = DownloadManager(self._sftp)
            self._downloader.add_progress_callback(self._on_download_progress)
            self._downloader.add_complete_callback(self._on_download_complete)
            self._downloader.add_error_callback(self._on_download_error)
            
            # 更新UI
            self._jump_chain = jump_chain
            self.server_info_widget.setConnectionInfo(jump_chain)
            self.server_info_widget.setConnected(True)
            
            # 获取主目录
            home = self._sftp.get_home()
            self._current_path = home
            self.path_edit.setText(home)
            self.server_info_widget.setCurrentPath(home)
            
            # 刷新文件列表
            self._refresh_file_list()
            
            self.statusBar().showMessage(f"已连接: {jump_chain}")
            
        except Exception as e:
            QMessageBox.critical(self, "连接失败", str(e))
    
    def _disconnect(self):
        """断开连接"""
        # 停止下载
        if self._downloader:
            self._downloader.stop()
            self._downloader = None
        
        # 关闭SFTP
        if self._sftp:
            self._sftp.close()
            self._sftp = None
        
        # 关闭连接
        if self._connection:
            self._connection.close()
            self._connection = None
        
        # 更新UI
        self._jump_chain = None
        self.server_info_widget.setConnected(False)
        self.file_list.setFiles([])
        self.path_edit.clear()
        
        self.statusBar().showMessage("已断开连接")
    
    def _navigate_to_path(self):
        """导航到指定路径"""
        path = self.path_edit.text().strip()
        if not path:
            return
        
        if not self._sftp:
            QMessageBox.warning(self, "提示", "请先连接服务器")
            return
        
        try:
            if self._sftp.is_dir(path):
                self._current_path = self._sftp.normalize_path(path)
                self.path_edit.setText(self._current_path)
                self.server_info_widget.setCurrentPath(self._current_path)
                self._refresh_file_list()
            else:
                QMessageBox.warning(self, "提示", f"'{path}' 不是有效目录")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法访问目录: {str(e)}")
    
    def _browse_home(self):
        """浏览主目录"""
        if self._sftp:
            home = self._sftp.get_home()
            self.path_edit.setText(home)
            self._navigate_to_path()
    
    def _refresh_file_list(self):
        """刷新文件列表（后台加载，不卡UI）"""
        if not self._sftp:
            return
        
        # 如果正在加载中，不要重复触发
        if self._loading_thread and self._loading_thread.is_alive():
            return
        
        # 显示加载状态
        self.file_list.setLoading(True)
        self.statusBar().showMessage("正在加载目录...")
        
        # 在后台线程中加载目录，避免大量文件时卡死UI
        current_path = self._current_path
        sftp = self._sftp
        
        def load_directory():
            try:
                files = sftp.list_dir(current_path)
                
                # 如果不是根目录，在列表顶部添加"返回上级"条目
                if current_path != "/":
                    parent = os.path.dirname(current_path.rstrip('/'))
                    if not parent:
                        parent = "/"
                    parent_entry = RemoteFile(
                        name="..",
                        path=parent,
                        is_dir=True,
                        size=0,
                        modify_time=datetime.now(),
                        permissions="d---------"
                    )
                    files.insert(0, parent_entry)
                
                # 通过信号在主线程更新UI
                self.files_loaded.emit(files, None)
            except Exception as e:
                self.files_loaded.emit(None, str(e))
        
        self._loading_thread = threading.Thread(target=load_directory, daemon=True)
        self._loading_thread.start()
    
    def _on_directory_loaded(self, files, error):
        """目录加载完成（在主线程执行）"""
        self._loading_thread = None
        
        if error:
            self.file_list.setLoading(False)
            QMessageBox.warning(self, "错误", f"无法列出目录: {error}")
            self.statusBar().showMessage("目录加载失败")
            return
        
        if files is not None:
            self.file_list.setFiles(files)
            self.file_list.setLoading(False)
            self.statusBar().showMessage(f"已加载 {len(files)} 个项目")
    
    def _on_file_double_click(self, file: RemoteFile):
        """双击文件"""
        if file.is_dir:
            # 进入目录
            self._current_path = file.path
            self.path_edit.setText(file.path)
            self.server_info_widget.setCurrentPath(file.path)
            self._refresh_file_list()
    
    def _on_selection_changed(self, files: list):
        """选择变化"""
        count = len(files)
        total_size = sum(f.size for f in files if not f.is_dir)
        
        self.selected_count_label.setText(
            f"已选文件 ({count}项, 共 {RemoteFile.format_size(total_size)})"
        )
        
        self.download_btn.setEnabled(count > 0)
        
        # 更新已选文件列表显示
        if files:
            file_names = [f"• {f.name} ({f.size_formatted})" for f in files[:5]]
            if len(files) > 5:
                file_names.append(f"... 还有 {len(files) - 5} 个文件")
            self.selected_list_label.setText("\n".join(file_names))
            self.selected_list_label.setStyleSheet("padding: 8px;")
        else:
            self.selected_list_label.setText("无选中文件")
            self.selected_list_label.setStyleSheet("color: #6c757d; padding: 8px;")
    
    def _clear_selection(self):
        """清空选择"""
        self.file_list.clearSelection()
    
    def _browse_local_path(self):
        """浏览本地保存路径"""
        path = QFileDialog.getExistingDirectory(
            self, "选择保存目录", 
            self.local_path_edit.text()
        )
        if path:
            self.local_path_edit.setText(path)
    
    def _start_download(self):
        """开始下载"""
        files = self.file_list.getCheckedFiles()
        if not files:
            return
        
        local_dir = self.local_path_edit.text()
        if not local_dir:
            QMessageBox.warning(self, "提示", "请选择保存目录")
            return
        
        # 创建下载任务
        for file in files:
            if file.is_dir:
                continue  # 暂不支持目录下载
            
            try:
                local_path = os.path.join(local_dir, file.name)
                task = self._downloader.create_task(
                    file.path, local_path, file.size
                )
                self._downloader.start_download(task.id)
                
                # 创建下载项组件
                self._add_download_widget(task)
                
            except Exception as e:
                QMessageBox.warning(
                    self, "错误", 
                    f"无法下载 {file.name}: {str(e)}"
                )
        
        # 清空选择
        self.file_list.clearSelection()
    
    def _add_download_widget(self, task: DownloadTask):
        """添加下载项组件"""
        widget = DownloadItemWidget(task)
        widget.pause_clicked.connect(self._on_pause_clicked)
        widget.resume_clicked.connect(self._on_resume_clicked)
        widget.cancel_clicked.connect(self._on_cancel_clicked)
        widget.open_clicked.connect(self._on_open_clicked)
        
        # 插入到stretch之前
        self.download_container_layout.insertWidget(
            self.download_container_layout.count() - 1, widget
        )
        self._download_widgets[task.id] = widget
    
    def _on_pause_clicked(self, task_id: str):
        """暂停下载"""
        if self._downloader:
            self._downloader.pause_download(task_id)
    
    def _on_resume_clicked(self, task_id: str):
        """恢复下载"""
        if self._downloader:
            self._downloader.resume_download(task_id)
    
    def _on_cancel_clicked(self, task_id: str):
        """取消下载"""
        if self._downloader:
            self._downloader.cancel_download(task_id)
    
    def _on_open_clicked(self, task_id: str):
        """打开文件"""
        task = self._downloader.get_task(task_id) if self._downloader else None
        if task and task.local_path:
            import subprocess
            import platform
            
            if platform.system() == "Windows":
                os.startfile(task.local_path)
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(["open", task.local_path])
            else:  # Linux
                subprocess.run(["xdg-open", task.local_path])
    
    def _on_download_progress(self, task_id: str, downloaded: int, total: int):
        """下载进度回调"""
        # 在主线程中更新UI
        pass  # 由定时器统一更新
    
    def _on_download_complete(self, task_id: str, local_path: str):
        """下载完成回调"""
        pass  # 由定时器统一更新
    
    def _on_download_error(self, task_id: str, error: str):
        """下载错误回调"""
        pass  # 由定时器统一更新
    
    def _update_progress(self):
        """更新下载进度"""
        if not self._downloader:
            return
        
        # 更新每个下载项
        for task_id, widget in self._download_widgets.items():
            task = self._downloader.get_task(task_id)
            if task:
                widget.update_task(task)
        
        # 更新总进度
        progress = self._downloader.get_total_progress()
        self.total_progress_label.setText(
            f"总进度: {progress['percentage']:.1f}% | "
            f"已完成: {progress['completed_count']}/{progress['total_count']}"
        )
    
    def _clear_completed_downloads(self):
        """清空已完成/已取消/失败的下载任务"""
        if not self._downloader:
            return
        
        finished_statuses = {DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELLED}
        to_remove = []
        
        for task_id, widget in self._download_widgets.items():
            task = self._downloader.get_task(task_id)
            if task and task.status in finished_statuses:
                to_remove.append(task_id)
        
        for task_id in to_remove:
            # 从界面移除
            widget = self._download_widgets.pop(task_id)
            self.download_container_layout.removeWidget(widget)
            widget.deleteLater()
            # 从下载管理器移除
            self._downloader.remove_task(task_id)
    
    def _show_about(self):
        """显示关于对话框"""
        QMessageBox.about(
            self, "关于",
            "<h3>SSH跳板机文件下载器</h3>"
            "<p>版本: 1.0.0</p>"
            "<p>一个支持跳板机连接的文件下载工具</p>"
            "<p>功能特性:</p>"
            "<ul>"
            "<li>SSH跳板机连接</li>"
            "<li>大文件断点续传</li>"
            "<li>多任务并行下载</li>"
            "<li>实时进度显示</li>"
            "</ul>"
        )
    
    def closeEvent(self, event):
        """关闭事件"""
        # 停止下载
        if self._downloader:
            self._downloader.stop()
        
        # 断开连接
        self._disconnect()
        
        # 停止定时器
        self._update_timer.stop()
        
        event.accept()
