# Finetuning/ui/main_window.py

import os
import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QCheckBox, QFrame, QSplitter, QMessageBox, QDockWidget,
    QButtonGroup, QRadioButton, QLabel, QGroupBox, QDialog, QSlider, QSizePolicy,
    QProgressDialog, QComboBox, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QAction, QKeySequence, QIcon, QGuiApplication

from core.app_model import AppModel
from core.image_manager import ImageManager
from core.semi_auto_mask_tools import build_frame_paths, explicit_seed_indices, resolve_seed_indices, saved_frame_indices
from .widgets.path_selector import PathSelector
from .widgets.image_canvas import ImageCanvas
from .widgets.preview_panel import PreviewPanel
from .widgets.progress_slider import ProgressSlider
from .widgets.settings_dialog import SettingsDialog
from .widgets.effects_dialog import EffectsDialog
from PyQt6.QtWidgets import QMessageBox # 确保已导入
from utils.helpers import get_base_path
from utils.cv_image_io import load_grayscale
from utils.path_utils import to_filesystem_path
from core.batch_processor import BatchProcessor
from ui.widgets.script_dialogs import ApplyMaskScriptDialog


# Seed 相关 UI 暂时下线 (2026-07-29)。当前流程用不到 Seed 模式, 而它在"显示选项"里
# 独占一整行, 路径面板展开时把右侧控制面板挤爆。
# 底层逻辑 (refresh_seed_cache / update_seed_status_label / Useful_script/seed_manager.py)
# 一行没动, 把下面这个常量改回 True 即可整行复原, 快捷键和配置都还在。
# 关闭时 seed 显示模式被钉在 "fast": 不画滑条彩线, 不画预览角标 (否则用户无从关掉它们)。
SHOW_SEED_CONTROLS = False


class MainWindow(QMainWindow):
    def __init__(self, parent=None, session_path: str = ""):
        super().__init__(parent)
        self._cli_session_path = session_path

        self.model = AppModel()
        self.image_manager = ImageManager()
        self.batch_processor = BatchProcessor()
        
        # 【修改 1】初始化一个属性来持有效果对话框的实例
        self.effects_dialog = None
        self.script_panel_dialog = None
        self.loaded_scripts = []

        self.active_actions = []

        self.set_application_icon()

        self.init_ui()
        self._create_menu()
        self._create_actions_and_shortcuts()
        self._connect_signals()
        
        self.initial_layout_states = {
            'main_window': self.saveState(),
            'main_splitter': self.main_splitter.saveState(),
            'right_splitter': self.right_splitter.saveState()
        }

        self._load_initial_settings()
        self.initial_state = self.saveState()  

    def set_application_icon(self):
        """加载并设置应用程序的图标。"""
        # script_dir = os.path.dirname(os.path.abspath(__file__))
        # icon_path = os.path.join(script_dir, 'resources', 'icons', 'app_icon.png')
        base_path = get_base_path()
        # 1. 根据操作系统平台确定图标文件名
        if sys.platform == 'darwin':
            # 'darwin' 是 macOS 的内部名称
            icon_filename = 'app_icon.icns'
            print("Detected macOS, attempting to load .icns icon.")
        else:
            # 适用于 Windows ('win32'), Linux ('linux') 等
            icon_filename = 'app_icon.png'
            print(f"Detected non-macOS ({sys.platform}), attempting to load .png icon.")

        # 2. 构建完整的图标路径
        icon_path = os.path.join(base_path, 'ui', 'resources', 'icons', icon_filename)
        
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            print("Application icon set successfully.")
        else:
            print(f"Warning: Application icon not found at '{icon_path}'")

    def init_ui(self):
        self.setWindowTitle("后处理工具 V9.6.0 (全新自定义+内置脚本)")
        # 获取主屏幕的可用几何尺寸（排除任务栏/Dock等）
        screen = QGuiApplication.primaryScreen()
        available_geometry = screen.availableGeometry()
        
        # 设置窗口为屏幕可用区域的90%
        window_width = int(available_geometry.width() * 0.9)
        window_height = int(available_geometry.height() * 0.9)
        
        # 计算居中位置
        x = available_geometry.x() + (available_geometry.width() - window_width) // 2
        y = available_geometry.y() + (available_geometry.height() - window_height) // 2
        
        self.setGeometry(x, y, window_width, window_height)
        # --- 修改结束 ---
        
        # 可选：设置最小尺寸以防止窗口过小
        self.setMinimumSize(500, 500)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        self.path_dock_widget = QDockWidget("路径设置 (可拖拽)", self)
        self.path_dock_widget.setObjectName("PathDockWidget")
        self.path_dock_widget.setAllowedAreas(Qt.DockWidgetArea.TopDockWidgetArea | Qt.DockWidgetArea.BottomDockWidgetArea)
        path_widget = QWidget()
        path_layout = QVBoxLayout(path_widget)
        self.original_path_selector = PathSelector("原图路径*:")
        self.denoised_path_selector = PathSelector("去噪图路径:")
        self.mask_path_selector = PathSelector("二值化图路径(参考):")
        self.save_path_selector = PathSelector("保存路径*:")
        self.import_button = QPushButton("加载/刷新图像 (I)")
        self.manifest_button = QPushButton("从 Manifest 加载 (M)")
        self.manifest_button.setToolTip("选择 MagicImageJ 导出目录中的 manifest.json，自动填充路径")
        path_layout.addWidget(self.original_path_selector)
        path_layout.addWidget(self.denoised_path_selector)
        path_layout.addWidget(self.mask_path_selector)
        path_layout.addWidget(self.save_path_selector)
        import_row = QHBoxLayout()
        import_row.addWidget(self.import_button)
        import_row.addWidget(self.manifest_button)
        path_layout.addLayout(import_row)
        self.path_dock_widget.setWidget(path_widget)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.path_dock_widget)
        
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        canvas_area = QFrame()
        canvas_area.setFrameShape(QFrame.Shape.StyledPanel)
        canvas_layout = QVBoxLayout(canvas_area)
        # self.canvas 必须保持这个名字: 全项目 20+ 处和 Useful_script/ 下十几个脚本硬引用它
        self.canvas = ImageCanvas(self.model, self.image_manager)
        self.compare_canvas = ImageCanvas(self.model, self.image_manager, is_mirror=True)
        self.compare_canvas.setVisible(False)
        self.canvas.attach_mirror(self.compare_canvas)

        self.canvas_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.canvas_splitter.addWidget(self.canvas)
        self.canvas_splitter.addWidget(self.compare_canvas)
        self.canvas_splitter.setChildrenCollapsible(False)
        # QSplitter(Horizontal) 默认竖直 policy 只是 Preferred, 而它取代的 QGraphicsView 是
        # Expanding。不补这一行, 多余高度会被 splitter 和下面的 ProgressSlider 平分, 页码标签
        # 被撑成一大块空白。
        self.canvas_splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.progress_slider = ProgressSlider()
        self.progress_slider.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        # 显式 stretch: 画布吃掉所有富余高度, 滑条+页码只占自己的 sizeHint
        canvas_layout.addWidget(self.canvas_splitter, 1)
        canvas_layout.addWidget(self.progress_slider, 0)
        
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.preview_panel = PreviewPanel(self.model, self.image_manager, canvas_widget=self.canvas)
        
        function_frame = QFrame()
        function_frame.setFrameShape(QFrame.Shape.StyledPanel)
        function_layout = QVBoxLayout(function_frame)
        # 收一点默认边距/行距 (Qt 默认 9~11px)。窗口按默认尺寸 (屏幕 90%) 启动时,
        # 整个面板就差这二三十像素放不下, 而收到 6px 肉眼看不出变挤。
        function_layout.setContentsMargins(6, 6, 6, 6)
        function_layout.setSpacing(6)

        display_group = QGroupBox("显示选项")
        display_layout = QVBoxLayout(display_group)
        display_layout.setContentsMargins(8, 6, 8, 6)
        display_layout.setSpacing(6)
        
        display_mode_layout = QHBoxLayout()
        self.hide_radio = QRadioButton("隐藏")
        self.area_radio = QRadioButton("面积")
        self.contour_radio = QRadioButton("轮廓")
        self.ants_radio = QRadioButton("蚂蚁线")
        
        self.display_mode_group = QButtonGroup(self)
        self.display_mode_group.addButton(self.hide_radio)
        self.display_mode_group.addButton(self.area_radio)
        self.display_mode_group.addButton(self.contour_radio)
        self.display_mode_group.addButton(self.ants_radio)

        display_mode_layout.addWidget(QLabel("查看模式:"))
        display_mode_layout.addWidget(self.hide_radio)
        display_mode_layout.addWidget(self.area_radio)
        display_mode_layout.addWidget(self.contour_radio)
        display_mode_layout.addWidget(self.ants_radio)

        general_options_layout = QHBoxLayout()
        region_options_layout = QHBoxLayout()
        seed_options_layout = QHBoxLayout()
        self.mask_invert_checkbox = QCheckBox("反相显示")
        
        self.lock_zoom_checkbox = QCheckBox("固定缩放")
        # --- START: 1. 新增 Mask 来源标签 ---
        # 默认文本会在加载文件时设置
        self.mask_source_label = QLabel("来源: N/A")
        self.mask_source_label.setObjectName("MaskSourceLabel")
        self.mask_source_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.seed_status_label = QLabel("Seed: N/A")
        self.seed_status_label.setObjectName("SeedStatusLabel")
        self.seed_status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.seed_status_label.setMinimumWidth(150)
        self.seed_visual_mode_button = QPushButton("Seed模式: 平衡")
        self.seed_visual_mode_button.setToolTip("切换 Seed 显示模式")
        self.seed_visual_mode_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.preview_seed_badges_checkbox = QCheckBox("预览Seed角标")
        self.preview_seed_badges_checkbox.setChecked(True)
        self.preview_seed_badges_checkbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.mask_source_label.setMinimumWidth(190)
        
        self.compare_view_checkbox = QCheckBox("对比视图")
        self.compare_view_checkbox.setToolTip(
            "右侧开一个只读镜像视图，缩放/平移与左侧同步。\n"
            "默认显示纯净图，用来对照蚂蚁线盖住的原始像素。"
        )
        self.compare_mode_combo = QComboBox()
        self.compare_mode_combo.setToolTip("右侧视图的查看模式")
        for label, key in (("纯净图", "hide"), ("面积", "area"), ("轮廓", "contour"), ("蚂蚁线", "ants")):
            self.compare_mode_combo.addItem(label, key)
        self.compare_mode_combo.setEnabled(False)
        self.compare_mode_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.region_mode_checkbox = QCheckBox("区域模式 (G)")
        self.region_mode_checkbox.setToolTip(
            "画「排除区域」——与 mask 完全独立的第二条通道（红/黄反向蚂蚁线）。\n"
            "\n"
            "· 自动保存**不需要关**：区域不走 mask 的写盘路径\n"
            "· 蚂蚁线照常显示，当前查看模式不会被改掉\n"
            "· 套索/多边形照用，Alt/Ctrl 减去，多笔自动累加\n"
            "· 此模式下 Ctrl+Z 只撤区域，W 只清区域，都不碰 mask\n"
            "\n"
            "用途：给「按区域去掉连通分量」提供区域；后续镜像填充重推也用它。"
        )
        self.clear_region_button = QPushButton("清除区域")
        self.clear_region_button.setToolTip("清空当前帧范围的排除区域")
        self.clear_region_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.auto_save_checkbox = QCheckBox("自动保存 (X)")

        # 行 1 (查看模式) 尾部收一个 stretch, 单选框不再被拉散; "来源" 靠右停在同一行,
        # 省下原来 seed 行才有的那 30px。
        display_mode_layout.addStretch()
        display_mode_layout.addWidget(self.mask_source_label)

        # 行 2: 视图开关。原来 6 个控件挤一行, 现在拆成两行, 每行都留得下空隙。
        general_options_layout.setSpacing(12)
        general_options_layout.addWidget(self.lock_zoom_checkbox)
        general_options_layout.addWidget(self.mask_invert_checkbox)
        general_options_layout.addWidget(self.compare_view_checkbox)
        general_options_layout.addWidget(self.compare_mode_combo)
        general_options_layout.addStretch()

        # "图像效果调整" 原来独占一个 "效果设置" QGroupBox: 一个按钮花掉 70px 竖直空间,
        # 是面板放不下的主因之一。它本来就是显示类操作, 并进本行右端。
        self.effects_button = QPushButton("图像效果调整 (C)") # 使用 QPushButton 更符合语义

        # 行 3: 区域模式 + 自动保存 (自动保存原来自己独占一行) + 效果按钮
        region_options_layout.setSpacing(12)
        region_options_layout.addWidget(self.region_mode_checkbox)
        region_options_layout.addWidget(self.clear_region_button)
        region_options_layout.addSpacing(16)
        region_options_layout.addWidget(self.auto_save_checkbox)
        region_options_layout.addStretch()
        region_options_layout.addWidget(self.effects_button)

        if SHOW_SEED_CONTROLS:
            seed_options_layout.setSpacing(10)
            seed_options_layout.addWidget(self.seed_visual_mode_button)
            seed_options_layout.addWidget(self.preview_seed_badges_checkbox)
            seed_options_layout.addStretch()
            seed_options_layout.addWidget(self.seed_status_label)
        else:
            # 不进任何 layout, 但要给个父窗口: 无父且未 show 的 QWidget 一旦被别处
            # show() 就会变成顶层窗口。对象全部留着, 外部脚本 (seed_manager 等) 仍能
            # setText / 读状态, 不会 AttributeError。
            for _seed_widget in (
                self.seed_visual_mode_button,
                self.preview_seed_badges_checkbox,
                self.seed_status_label,
            ):
                _seed_widget.setParent(display_group)
                _seed_widget.setVisible(False)

        self.filename_display_layout = QHBoxLayout()
        self.filename_label_title = QLabel("当前文件:")
        self.filename_label_value = QLabel("N/A")
        
        # 策略：让value-label水平扩展，并将其内部文本推到右侧
        # QLabel 默认会使用 ElideRight (末尾...) 来处理溢出文本
        self.filename_label_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.filename_label_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.filename_label_value.setToolTip("当前正在编辑的图像文件名")
        
        self.filename_display_layout.addWidget(self.filename_label_title)
        self.filename_display_layout.addWidget(self.filename_label_value)

        display_layout.addLayout(display_mode_layout)
        display_layout.addLayout(general_options_layout)
        display_layout.addLayout(region_options_layout)
        if SHOW_SEED_CONTROLS:
            display_layout.addLayout(seed_options_layout)
        display_layout.addLayout(self.filename_display_layout)

        tools_group = QGroupBox("编辑工具")
        tools_layout = QVBoxLayout(tools_group)
        tools_layout.setContentsMargins(8, 6, 8, 6)
        tools_layout.setSpacing(6)
        tool_buttons_layout = QHBoxLayout()
        self.lasso_button = QPushButton("套索 (+/Q)")
        self.lasso_subtract_button = QPushButton("套索 (-)")
        self.polygon_button = QPushButton("多边形 (+/P)")
        self.polygon_subtract_button = QPushButton("多边形 (-)")
        self.erase_selection_button = QPushButton("橡皮擦(E)")

        self.lasso_button.setCheckable(True)
        self.lasso_subtract_button.setCheckable(True)
        self.polygon_button.setCheckable(True)
        self.polygon_subtract_button.setCheckable(True)
        self.erase_selection_button.setCheckable(True)

        self.tool_button_group = QButtonGroup(self)
        self.tool_button_group.addButton(self.lasso_button)
        self.tool_button_group.addButton(self.lasso_subtract_button)
        self.tool_button_group.addButton(self.polygon_button)
        self.tool_button_group.addButton(self.polygon_subtract_button)
        self.tool_button_group.addButton(self.erase_selection_button)

        self.lasso_button.setChecked(True)
        tool_buttons_layout.addWidget(self.lasso_button)
        tool_buttons_layout.addWidget(self.lasso_subtract_button)
        tool_buttons_layout.addWidget(self.polygon_button)
        tool_buttons_layout.addWidget(self.polygon_subtract_button)
        tool_buttons_layout.addWidget(self.erase_selection_button)
        
        # --- START: 新增橡皮擦大小滑块 ---
        tool_options_layout = QHBoxLayout()
        # eraser_size_layout = QHBoxLayout()
        self.eraser_size_label = QLabel(f"橡皮擦: {self.model.eraser_size}px")
        self.eraser_size_label.setMinimumWidth(80) # 防止标签跳动
        self.eraser_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.eraser_size_slider.setRange(1, 200) # 设置橡皮擦大小范围
        self.eraser_size_slider.setValue(self.model.eraser_size)
        tool_options_layout.addWidget(self.eraser_size_label)
        tool_options_layout.addWidget(self.eraser_size_slider)
        tool_options_layout.addSpacing(20) # 添加一点间距
        # 新增的 "添加模式" 复选框
        self.selection_add_mode_checkbox = QCheckBox("添加模式")
        self.selection_add_mode_checkbox.setToolTip("勾选后，套索和多边形工具将默认用于添加选区（无需按Shift）")
        tool_options_layout.addWidget(self.selection_add_mode_checkbox)

        
        # 4 个动作按钮改成 2x2: 竖排要 4 行 (~145px), 这是右侧面板高度的大头。
        action_buttons_layout = QGridLayout()
        action_buttons_layout.setHorizontalSpacing(8)
        action_buttons_layout.setVerticalSpacing(6)

        self.toggle_mask_source_button = QPushButton("切换Mask来源 (T)")
        self.clear_button = QPushButton("清除Mask (W)")
        self.save_button = QPushButton("保存 (Ctrl+S)")
        self.save_and_next_button = QPushButton("保存并下一张 (S or 双击)")

        for _action_button in (
            self.toggle_mask_source_button,
            self.clear_button,
            self.save_button,
            self.save_and_next_button,
        ):
            _action_button.setMinimumHeight(32)

        action_buttons_layout.addWidget(self.toggle_mask_source_button, 0, 0)
        action_buttons_layout.addWidget(self.clear_button, 0, 1)
        action_buttons_layout.addWidget(self.save_button, 1, 0)
        action_buttons_layout.addWidget(self.save_and_next_button, 1, 1)
        tools_layout.addLayout(tool_buttons_layout)
        tools_layout.addLayout(tool_options_layout) # 将滑块工具添加到工具布局中
        tools_layout.addLayout(action_buttons_layout)

        nav_layout = QHBoxLayout()
        self.prev_button = QPushButton("上一张 (A/←)")
        self.next_button = QPushButton("下一张 (D/→)")
        nav_layout.addWidget(self.prev_button)
        nav_layout.addWidget(self.next_button)

        function_layout.addWidget(display_group)
        function_layout.addWidget(tools_group)
        function_layout.addStretch()
        function_layout.addLayout(nav_layout)
        function_frame.setLayout(function_layout)

        # 右侧控制面板套一层 QScrollArea。路径面板展开会吃掉 200+ px 竖直空间, 直接挂在
        # splitter 上时 QVBoxLayout 只能把按钮压到互相重叠 (截图时尤其难看)。有滚动条兜底
        # 后, 空间不够最多是出现滚动条, 不会再挤压任何控件。
        self.function_frame = function_frame
        self.function_scroll = QScrollArea()
        self.function_scroll.setWidgetResizable(True)
        self.function_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.function_scroll.setWidget(function_frame)
        self.function_scroll.setMinimumHeight(200)

        self.right_splitter.addWidget(self.preview_panel)
        self.right_splitter.addWidget(self.function_scroll)
        # 富余高度全给预览图, 控制面板保持自然高度 (真正的初值在 showEvent 里按
        # sizeHint 现算, 见 _apply_default_right_split)
        self.right_splitter.setStretchFactor(0, 1)
        self.right_splitter.setStretchFactor(1, 0)
        self.right_splitter.setSizes([420, 470])
        self.main_splitter.addWidget(canvas_area)
        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.setSizes([1200, 600])
        main_layout.addWidget(self.main_splitter)
    
    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_right_split_applied", False):
            self._right_split_applied = True
            # 延后到本轮布局结束: showEvent 里 splitter 还可能是旧几何
            QTimer.singleShot(0, self._apply_default_right_split)

    def _apply_default_right_split(self):
        """控制面板拿它自然需要的高度, 剩下的全给预览图。

        QSplitter.setSizes 是按比例缩放的, 写死 [600, 200] 等于把控制面板永久钉在
        25% —— 路径面板一展开就不够放, 按钮被压成一团。这里直接量"内容还差多少",
        从预览图那边匀过来 (匀到预览图的下限为止), 多了再还回去; 手柄宽度、边框这些
        都不用自己算。
        """
        if self.right_splitter.height() <= 0:
            return

        # 横向: 面板窄于内容最小宽度就会冒出横向滚动条 (5 个工具按钮那一行最宽), 横条
        # 还要再吃掉一截高度。给右侧留个下限让画布去让宽度 —— 直接量"还差多少", 免得
        # 自己算滚动条/边框/splitter 那几层 chrome。上限是窗口一半, 防止画布被吃光。
        for _ in range(3):
            deficit = (self.function_frame.minimumSizeHint().width()
                       - self.function_scroll.viewport().width())
            if deficit <= 0:
                break
            new_min = min(self.right_splitter.width() + deficit, max(320, self.width() // 2))
            if new_min <= self.right_splitter.minimumWidth():
                break
            self.right_splitter.setMinimumWidth(new_min)
            main_sizes = self.main_splitter.sizes()
            if len(main_sizes) >= 2:
                # 手动推一把, 否则这一轮量到的还是旧宽度
                self.main_splitter.setSizes(
                    [max(0, main_sizes[0] - deficit), main_sizes[1] + deficit])

        # 预览面板自己的最小高度 (标题条 + 3 行缩略图) 才是真下限, 写个更小的常数
        # 只会让下面的循环空转 4 圈。
        preview_min = max(120, self.preview_panel.minimumSizeHint().height())
        scroll_min = self.function_scroll.minimumHeight()
        for _ in range(4):
            delta = (self.function_frame.sizeHint().height()
                     - self.function_scroll.viewport().height())
            if abs(delta) <= 2:
                break
            sizes = self.right_splitter.sizes()
            if len(sizes) < 2:
                return
            if delta > 0:
                shift = min(delta, max(0, sizes[0] - preview_min))
            else:
                shift = -min(-delta, max(0, sizes[1] - scroll_min))
            if shift == 0:
                break
            self.right_splitter.setSizes([sizes[0] - shift, sizes[1] + shift])
        if hasattr(self, "initial_layout_states"):
            self.initial_layout_states['right_splitter'] = self.right_splitter.saveState()

    def _create_menu(self):
        self.menu_bar = self.menuBar()
        file_menu = self.menu_bar.addMenu("文件(&F)")

        self.import_action = QAction("加载/刷新图像 (I)", self)
        self.import_action.triggered.connect(self.import_images)
        file_menu.addAction(self.import_action)
        
        file_menu.addSeparator()
        self.exit_action = QAction("退出(&Q)", self)
        self.exit_action.triggered.connect(self.close)
        file_menu.addAction(self.exit_action)

        edit_menu = self.menu_bar.addMenu("编辑(&E)")
        self.undo_action = QAction("撤销", self)
        self.undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        self.undo_action.triggered.connect(self.canvas.undo)
        edit_menu.addAction(self.undo_action)

        # --- [MODIFIED] 动态加载脚本菜单 ---
        scripts_menu = self.menu_bar.addMenu("脚本(&Scripts)")
        self._populate_scripts_menu(scripts_menu)
        
        view_menu = self.menu_bar.addMenu("视图(&V)")
        self.toggle_path_dock_action = self.path_dock_widget.toggleViewAction()
        self.toggle_path_dock_action.setText("显示/隐藏路径面板")
        view_menu.addAction(self.toggle_path_dock_action)
        
        view_menu.addSeparator()
        self.restore_layout_action = QAction("恢复默认布局", self)
        self.restore_layout_action.triggered.connect(self.restore_layout)
        view_menu.addAction(self.restore_layout_action)  
        settings_menu = self.menu_bar.addMenu("设置(&S)")
        self.settings_action = QAction("打开设置...", self)
        self.settings_action.triggered.connect(self.open_settings_dialog)
        settings_menu.addAction(self.settings_action)

    def _populate_scripts_menu(self, menu):
        """动态加载 Useful_script/ 目录中的脚本并按工作流分类。"""
        from Useful_script.script_loader import group_scripts_by_category, load_scripts
        
        # 获取 Useful_script 目录的绝对路径
        base_path = get_base_path()
        scripts_dir = os.path.join(base_path, 'Useful_script')
        
        scripts = load_scripts(scripts_dir)
        self.loaded_scripts = scripts
        
        if not scripts:
            no_script_action = QAction("(无可用脚本)", self)
            no_script_action.setEnabled(False)
            menu.addAction(no_script_action)
            return

        panel_action = QAction("打开脚本面板...", self)
        panel_action.setToolTip("以非模态面板方式按类别浏览和运行脚本")
        panel_action.triggered.connect(self.open_script_panel)
        menu.addAction(panel_action)
        menu.addSeparator()
        
        for category, category_scripts in group_scripts_by_category(scripts):
            category_menu = menu.addMenu(category)
            for script in category_scripts:
                action = QAction(script['name'], self)
                if script['description']:
                    action.setToolTip(script['description'])
                
                action.triggered.connect(lambda checked, s=script: self._run_script_info(s))
                category_menu.addAction(action)

    def _run_script_info(self, script):
        run_func = script.get('run')
        if callable(run_func):
            run_func(self)

    def open_script_panel(self):
        from Useful_script.script_loader import load_scripts
        from ui.widgets.script_panel import ScriptPanelDialog

        base_path = get_base_path()
        scripts_dir = os.path.join(base_path, 'Useful_script')
        self.loaded_scripts = load_scripts(scripts_dir)

        if self.script_panel_dialog is None:
            self.script_panel_dialog = ScriptPanelDialog(self.loaded_scripts, self)
            self.script_panel_dialog.run_script_requested.connect(self._run_script_info)
        else:
            self.script_panel_dialog.set_scripts(self.loaded_scripts)

        self.script_panel_dialog.show()
        self.script_panel_dialog.raise_()
        self.script_panel_dialog.activateWindow()

    def _create_actions_and_shortcuts(self):
        for action in self.active_actions:
            self.removeAction(action)
        self.active_actions.clear()

        def create_shortcut(key_name, function):
            shortcut_str = self.model.get_keybinding(key_name)
            if not shortcut_str: return
            action = QAction(self)
            shortcuts = [QKeySequence(key.strip()) for key in shortcut_str.replace(';', ',').split(',')]
            action.setShortcuts(shortcuts)
            action.triggered.connect(function)
            self.addAction(action)
            self.active_actions.append(action)
        
        key_map = {
            'next_image': self.model.increment_index,
            'prev_image': self.model.decrement_index,
            'save': self.canvas.save_current_mask,
            'draw_mode': lambda: self.model.set_selection_tool("lasso"),
            'polygon_mode': lambda: self.model.set_selection_tool("polygon"),
            'erase_mode': lambda: self.model.set_selection_tool("erase"),
            'clear_mask': self.canvas.clear_current_selection,
            'toggle_mask': self.toggle_mask_visibility,
            'import_files': self.import_images,
            'save_and_next': self.save_and_next,
            'next_binary_dataset': self.load_next_binary_dataset,
            'previous_binary_dataset': self.load_previous_binary_dataset,
            'skip_current_binary_dataset': self.skip_current_binary_dataset,
            'auto_save': lambda: self.model.set_auto_save(not self.model.auto_save),
            'high_contrast': self.toggle_quick_contrast,
            'open_effects_panel': self.open_effects_chooser,
            'toggle_image_source': self.model.toggle_image_source,
            'toggle_path_panel':self.toggle_path_dock_action.trigger,
            'toggle_mask_source':self.model.toggle_mask_source,
            'cycle_seed_visual_mode': self.cycle_seed_visual_mode,
            'toggle_compare_view': lambda: self.compare_view_checkbox.toggle(),
            'toggle_region_mode': lambda: self.region_mode_checkbox.toggle(),
        }
        
        for key, func in key_map.items():
            create_shortcut(key, func)
        
        # 1. 更新“加载/刷新图像”菜单
        shortcut_str = self.model.get_keybinding('import_files')
        menu_text = "加载/刷新图像"
        if shortcut_str:
            display_shortcut = shortcut_str.split(';')[0].split(',')[0].strip()
            menu_text += f" ({display_shortcut})"
        self.import_action.setText(menu_text)

        # 2. 更新“显示/隐藏路径面板”菜单
        shortcut_str = self.model.get_keybinding('toggle_path_panel')
        menu_text = "显示/隐藏路径面板"
        if shortcut_str:
            display_shortcut = shortcut_str.split(';')[0].split(',')[0].strip()
            menu_text += f" ({display_shortcut})"
        self.toggle_path_dock_action.setText(menu_text)
        self._update_shortcut_labels()

    def _primary_shortcut_text(self, key_name):
        shortcut_str = self.model.get_keybinding(key_name)
        if not shortcut_str:
            return ""
        return shortcut_str.split(';')[0].split(',')[0].strip()

    def _update_shortcut_labels(self):
        panel_shortcut = self._primary_shortcut_text('open_effects_panel')
        contrast_shortcut = self._primary_shortcut_text('high_contrast')
        mode_shortcut = self._primary_shortcut_text('cycle_seed_visual_mode')
        mask_toggle_shortcut = self._primary_shortcut_text('toggle_mask')

        panel_text = "\u56fe\u50cf\u6548\u679c\u8c03\u6574"
        if panel_shortcut:
            panel_text += f" ({panel_shortcut})"
        self.effects_button.setText(panel_text)

        tooltip_parts = []
        if contrast_shortcut:
            tooltip_parts.append(f"\u5feb\u901f\u5bf9\u6bd4\u5ea6: {contrast_shortcut}")
        if panel_shortcut:
            tooltip_parts.append(f"\u6253\u5f00\u9762\u677f: {panel_shortcut}")
        if tooltip_parts:
            self.effects_button.setToolTip(" | ".join(tooltip_parts))
        if mask_toggle_shortcut:
            shortcut_hint = f"快捷切换蚂蚁线/隐藏: {mask_toggle_shortcut}"
            self.hide_radio.setToolTip(shortcut_hint)
            self.ants_radio.setToolTip(shortcut_hint)
        else:
            self.hide_radio.setToolTip("")
            self.ants_radio.setToolTip("")
        self._update_seed_visual_mode_button_text(mode_shortcut)

    def _seed_visual_mode_label(self, mode):
        return {
            "fast": "极速",
            "balanced": "平衡",
            "info": "信息",
        }.get(mode, "平衡")

    def _update_seed_visual_mode_button_text(self, shortcut_text=None):
        mode = getattr(self.model, "seed_visual_mode", "balanced")
        label = self._seed_visual_mode_label(mode)
        text = f"Seed模式: {label}"
        if shortcut_text:
            text += f" ({shortcut_text})"
        self.seed_visual_mode_button.setText(text)
        self.seed_visual_mode_button.setToolTip(
            "极速: 仅显示当前帧 Seed 文本\n"
            "平衡: 显示当前帧文本 + 底部滑条彩线\n"
            "信息: 额外显示预览角标"
        )

    def apply_seed_visual_mode(self, mode, persist=True):
        valid_modes = {"fast", "balanced", "info"}
        if mode not in valid_modes:
            mode = "balanced"
        if not SHOW_SEED_CONTROLS:
            # 控件下线时钉死在 fast: 只留内部状态, 不画滑条彩线/预览角标 ——
            # 否则用户看得见 seed 视觉却没有任何开关能关掉它。
            # persist 一并关掉: 别把这个临时值写进配置, 否则将来把控件放回来时
            # 用户原本的 balanced/info 已经被覆盖成 fast 了。
            mode = "fast"
            persist = False

        show_slider_markers = mode in {"balanced", "info"}
        show_preview_badges = mode == "info"

        self.model.show_slider_seed_markers = show_slider_markers
        self.model.show_preview_seed_badges = show_preview_badges
        self.model.set_seed_visual_mode(mode)

        self.preview_seed_badges_checkbox.blockSignals(True)
        self.preview_seed_badges_checkbox.setChecked(show_preview_badges)
        self.preview_seed_badges_checkbox.blockSignals(False)
        self.preview_seed_badges_checkbox.setEnabled(mode == "info")

        if SHOW_SEED_CONTROLS and self.model.config.has_section("Preview"):
            self.model.config.set("Preview", "seed_visual_mode", mode)

        self._update_seed_visual_mode_button_text(
            self._primary_shortcut_text('cycle_seed_visual_mode')
        )
        self.refresh_seed_cache()
        self.update_seed_status_label()
        self.preview_panel.update_previews(self.model.current_index)

        if persist:
            self._safe_save_config()

    def cycle_seed_visual_mode(self):
        order = ["fast", "balanced", "info"]
        current = getattr(self.model, "seed_visual_mode", "balanced")
        try:
            next_mode = order[(order.index(current) + 1) % len(order)]
        except ValueError:
            next_mode = "balanced"
        self.apply_seed_visual_mode(next_mode, persist=True)

    @pyqtSlot(str, str)
    def _update_model_path(self, key, new_path):
        """一个专门用来更新模型中路径配置的槽函数"""
        # 使用 self.model.config.set 来更新内存中的配置
        self.model.config.set('Paths', key, new_path)
        print(f"Model path '{key}' updated to: {new_path}")

    def _connect_signals(self):
        self.import_button.clicked.connect(self.import_images)
        self.manifest_button.clicked.connect(self.load_from_manifest)
        self.prev_button.clicked.connect(self.model.decrement_index)
        self.next_button.clicked.connect(self.model.increment_index)
        self.progress_slider.slider.valueChanged.connect(self.model.set_current_index)
        
        self.clear_button.clicked.connect(self.canvas.clear_current_selection)
        self.save_button.clicked.connect(self.canvas.save_current_mask)
        self.save_and_next_button.clicked.connect(self.save_and_next)

        self.toggle_mask_source_button.clicked.connect(self.model.toggle_mask_source)
        
        self.canvas.save_and_next_requested.connect(self.save_and_next)

        self.lasso_button.toggled.connect(lambda checked: self.model.set_selection_tool("lasso") if checked else None)
        self.lasso_subtract_button.toggled.connect(lambda checked: self.model.set_selection_tool("lasso_subtract") if checked else None)
        self.polygon_button.toggled.connect(lambda checked: self.model.set_selection_tool("polygon") if checked else None)
        self.polygon_subtract_button.toggled.connect(lambda checked: self.model.set_selection_tool("polygon_subtract") if checked else None)
        self.erase_selection_button.toggled.connect(lambda checked: self.model.set_selection_tool("erase") if checked else None)
        
        # --- START: 连接橡皮擦滑块 ---
        self.eraser_size_slider.valueChanged.connect(self.model.set_eraser_size)
        self.model.eraser_size_changed.connect(self.on_eraser_size_changed)
        self.selection_add_mode_checkbox.toggled.connect(self.model.set_selection_add_mode)
        self.model.selection_add_mode_changed.connect(self.selection_add_mode_checkbox.setChecked)

        self.hide_radio.toggled.connect(lambda checked: self.model.set_display_mode("hide") if checked else None)
        self.area_radio.toggled.connect(lambda checked: self.model.set_display_mode("area") if checked else None)
        self.contour_radio.toggled.connect(lambda checked: self.model.set_display_mode("contour") if checked else None)
        self.ants_radio.toggled.connect(lambda checked: self.model.set_display_mode("ants") if checked else None)

        self.auto_save_checkbox.toggled.connect(self.model.set_auto_save)
        self.effects_button.clicked.connect(self.open_effects_chooser)
        self.mask_invert_checkbox.toggled.connect(self.model.set_mask_invert)
        self.lock_zoom_checkbox.toggled.connect(self.model.set_zoom_locked)
        self.compare_view_checkbox.toggled.connect(self.on_compare_view_toggled)
        self.compare_mode_combo.currentIndexChanged.connect(self.on_compare_mode_changed)
        self.region_mode_checkbox.toggled.connect(self.on_region_mode_toggled)
        self.clear_region_button.clicked.connect(self.on_clear_region)
        self.seed_visual_mode_button.clicked.connect(self.cycle_seed_visual_mode)
        self.preview_seed_badges_checkbox.toggled.connect(lambda checked: setattr(self.model, "show_preview_seed_badges", checked))
        self.preview_seed_badges_checkbox.toggled.connect(self._on_preview_seed_badges_toggled)

        self.model.index_changed.connect(self.on_index_changed)
        self.model.files_changed.connect(self.on_files_changed)
        self.model.tool_changed.connect(self.on_tool_changed)
        
        self.model.auto_save_changed.connect(self.auto_save_checkbox.setChecked)
        self.model.effects_changed.connect(self.canvas.on_effects_changed)
        self.model.display_mode_changed.connect(self.on_display_mode_changed)
        self.model.seed_visual_mode_changed.connect(
            lambda _: self._update_seed_visual_mode_button_text(
                self._primary_shortcut_text('cycle_seed_visual_mode')
            )
        )
        
        self.model.zoom_lock_changed.connect(self.lock_zoom_checkbox.setChecked)

        self.model.mask_updated.connect(self.canvas.update_selection_display)
        self.model.preview_effects_changed.connect(self.canvas.on_preview_effects_changed)
        self.model.display_mode_changed.connect(self.canvas.update_selection_display)

        # 新增：当Mask加载源切换时，强制重载当前图像
        self.model.mask_source_changed.connect(
            lambda:self.canvas.load_image(self.model.current_index)
            )
        # 更换加载源时，更新标签文本
        self.model.mask_source_changed.connect(self.update_mask_source_label)
        self.model.mask_saved.connect(lambda index: self.refresh_seed_cache(index))
        self.model.mask_saved.connect(lambda _index: self.update_seed_status_label())

        self.model.image_source_changed.connect(self.canvas.on_image_source_changed)
        self.model.mask_updated.connect(lambda: self.preview_panel.update_previews(self.model.current_index))
        
        # 当用户通过UI选择新路径时，立即更新AppModel
        self.original_path_selector.path_selected.connect(
            lambda path: self._update_model_path('original_path', path)
        )
        self.denoised_path_selector.path_selected.connect(
            lambda path: self._update_model_path('denoised_path', path)
        )
        self.mask_path_selector.path_selected.connect(
            lambda path: self._update_model_path('mask_path', path)
        )
        self.save_path_selector.path_selected.connect(
            lambda path: self._update_model_path('save_path', path)
        )

    def toggle_mask_visibility(self):
        self.model.toggle_mask_visibility()

    @pyqtSlot(bool)
    def on_region_mode_toggled(self, enabled):
        """开/关排除区域绘制模式。

        刻意什么状态都不改 —— 不碰 auto_save, 不碰 display_mode, 不碰 selection_tool。
        老脚本正是因为强改这些又不还原, 才留下一串副作用。
        """
        self.model.set_region_mode(enabled)
        self.canvas.setFocus()

    def on_clear_region(self):
        self.canvas.clear_region()
        self.canvas.setFocus()

    def on_compare_view_toggled(self, enabled):
        """开/关右侧只读对比视图。"""
        self.compare_canvas.setVisible(enabled)
        self.compare_mode_combo.setEnabled(enabled)
        if not enabled:
            return
        # 五五开; 用户之后拖 splitter 的比例本轮会保留
        width = max(self.canvas_splitter.width(), 2)
        self.canvas_splitter.setSizes([width // 2, width // 2])
        # 刚变可见, 主视图还没有任何事件会触发推送, 这里显式同步一次内容+视角
        self.canvas.sync_mirror_now()

    @pyqtSlot()
    def on_compare_mode_changed(self):
        self.compare_canvas.set_display_mode_override(self.compare_mode_combo.currentData())

    def _on_preview_seed_badges_toggled(self, checked):
        current_mode = getattr(self.model, "seed_visual_mode", "balanced")
        if checked and current_mode != "info":
            self.apply_seed_visual_mode("info", persist=True)
            return
        if not checked and current_mode == "info":
            self.apply_seed_visual_mode("balanced", persist=True)
            return
        self.model.show_preview_seed_badges = checked
        self.preview_panel.update_previews(self.model.current_index)

    def toggle_quick_contrast(self):
        if self.model.current_index >= 0:
            self.canvas.push_undo_state_for_effects()
        self.model.toggle_quick_contrast()
        if self.effects_dialog is not None:
            current_base_pixmap = self.canvas._denoised_pixmap if (self.model.show_denoised and self.canvas._denoised_pixmap) else self.canvas._original_pixmap
            if current_base_pixmap:
                self.effects_dialog.set_current_pixmap(current_base_pixmap)
            self.effects_dialog._load_settings_to_ui(self.model.effect_settings)

    def run_script_clean_mask(self):
        """调用 BatchProcessor 执行清洗逻辑"""
        mask_files = self.model._mask_files
        save_dir = self.model.get_path('save_path')

        if not mask_files or not save_dir:
            QMessageBox.warning(self, "路径未设置", "请确保已加载 Mask 路径且设置了 Save Path。")
            return

        count = len(mask_files)
        reply = QMessageBox.question(self, "批量处理确认", 
                                     f"即将处理 {count} 张图像，结果将覆盖保存路径中的文件。\n是否继续？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return

        # 进度条
        progress = QProgressDialog("正在清洗 Mask...", "取消", 0, count, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        # 定义回调更新进度
        def progress_cb(current, total):
            if progress.wasCanceled(): return False
            progress.setValue(current + 1)
            QApplication.processEvents() # 保持界面响应
            return True

        # [CALL] 调用核心逻辑
        processed = self.batch_processor.run_clean_masks(mask_files, save_dir, progress_cb)
        
        progress.setValue(count)
        
        # 刷新界面
        if self.model.load_from_save_path:
             self.canvas.load_image(self.model.current_index)
             self.preview_panel.update_previews(self.model.current_index)

        QMessageBox.information(self, "完成", f"已清洗 {processed} 张 Mask。")

    def run_script_apply_mask(self):
        """
        弹出对话框配置路径，然后调用 BatchProcessor 执行抠图。
        """
        # 1. 准备默认路径 (为了方便用户，预填当前项目的路径)
        # 注意：用户可能想用已保存的 Cleaned Mask，所以 Mask 默认路径优先设为 Save Path
        default_mask = self.model.get_path('save_path') or self.model.get_path('mask_path')
        default_img = self.model.get_path('original_path')
        # 结果路径默认设为原图路径下的 "masked_output" 文件夹
        default_save = os.path.join(default_img, "masked_output") if default_img else ""

        # 2. 弹出配置对话框
        dialog = ApplyMaskScriptDialog(default_mask, default_img, default_save, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        # 3. 获取配置
        mask_path, img_path, save_path = dialog.get_paths()
        
        # 确保保存目录存在
        if not os.path.exists(to_filesystem_path(save_path)):
            try:
                os.makedirs(to_filesystem_path(save_path), exist_ok=True)
            except OSError as e:
                QMessageBox.critical(self, "错误", f"无法创建保存目录:\n{e}")
                return

        # 4. 准备进度条
        # 我们需要先统计一下文件数量来设置进度条最大值，但 batch_processor 里会再算一次。
        # 为了简单，我们先大概估算或让 batch_processor 处理。
        # 这里为了 UI 响应，我们在 BatchProcessor 里并没有计算 total 的逻辑暴露出来。
        # 简单起见，我们先获取一下 Mask 数量用于进度条显示。
        from core.image_manager import ImageManager # 临时导入
        total_files = len(ImageManager.get_image_files(mask_path))
        
        progress = QProgressDialog("正在批量抠图...", "取消", 0, total_files, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        
        def progress_cb(current, total):
            if progress.wasCanceled(): return False
            progress.setValue(current + 1)
            QApplication.processEvents()
            return True

        # 5. [CALL] 调用核心逻辑
        processed = self.batch_processor.run_apply_mask_to_images(
            mask_path, img_path, save_path, progress_cb
        )
        
        progress.setValue(total_files)
        QMessageBox.information(self, "完成", f"处理完成！\n共生成 {processed} 张抠图结果。\n保存在: {save_path}")

    # --- [MODIFIED] 打开效果对话框时传递 Pixmap ---
    def open_effects_chooser(self):
        if self.model.current_index < 0:
            QMessageBox.warning(self, "提示", "请先加载图像。")
            return

        # 获取当前正在显示的底图 (可能是原图，也可能是去噪图)
        current_base_pixmap = self.canvas._denoised_pixmap if (self.model.show_denoised and self.canvas._denoised_pixmap) else self.canvas._original_pixmap

        if self.effects_dialog is None or not self.effects_dialog.isVisible():
            # [CHANGE] 传递 current_base_pixmap 给 Dialog
            self.effects_dialog = EffectsDialog(self.model, self, current_pixmap=current_base_pixmap)

            def apply_new_settings(settings):
                self.canvas.push_undo_state_for_effects()
                self.model.update_effect_settings(settings)
            
            self.effects_dialog.settings_applied.connect(apply_new_settings)
            self.effects_dialog.finished.connect(self.on_effects_dialog_finished)

            self.effects_dialog.show()
        else:
            # 如果对话框已经打开，更新它内部引用的图片（防止用户换图了但对话框还在用旧图计算Auto）
            self.effects_dialog.current_pixmap = current_base_pixmap
            self.effects_dialog.raise_()
            self.effects_dialog.activateWindow()

    # --- START: 新增橡皮擦滑块的槽函数 ---
    @pyqtSlot(int)
    def on_eraser_size_changed(self, size):
        # 更新标签
        self.eraser_size_label.setText(f"橡皮擦: {size}px")
        # 更新滑块位置（防止循环触发，先阻断信号）
        self.eraser_size_slider.blockSignals(True)
        self.eraser_size_slider.setValue(size)
        self.eraser_size_slider.blockSignals(False)


    @pyqtSlot(str)
    def on_tool_changed(self, tool):
        self.canvas.set_tool(tool)
        if tool == 'lasso':
            self.lasso_button.setChecked(True)
        elif tool == 'polygon':
            self.polygon_button.setChecked(True)
        elif tool == 'erase':
            self.erase_selection_button.setChecked(True)
        elif tool == 'lasso_subtract':
            self.lasso_subtract_button.setChecked(True)
        elif tool == 'polygon_subtract':
            self.polygon_subtract_button.setChecked(True)

    @pyqtSlot(str)
    def on_display_mode_changed(self, mode):
        if mode == "hide":
            self.hide_radio.setChecked(True)
        elif mode == "area":
            self.area_radio.setChecked(True)
        elif mode == "contour":
            self.contour_radio.setChecked(True)
        elif mode == "ants":
            self.ants_radio.setChecked(True)

    def _update_navigation_controls(self):
        total_files = len(getattr(self.model, "_original_files", []))
        index = self.model.current_index
        has_valid_frame = total_files > 0 and 0 <= index < total_files
        self.prev_button.setEnabled(has_valid_frame and index > 0)
        self.next_button.setEnabled(has_valid_frame and index < total_files - 1)

    @pyqtSlot(int)
    def on_index_changed(self, index):
        self._update_navigation_controls()
        if index < 0: 
            # 如果索引无效 (例如没有文件)，清空标签并返回
            self.filename_label_value.setText("N/A")
            self.filename_label_value.setToolTip("")
            self.seed_status_label.setText("Seed: N/A")
            # 确保滑块标签也更新
            self.progress_slider.set_value(index)
            self.progress_slider.update_label()
            return
        self.progress_slider.slider.blockSignals(True)
        self.progress_slider.set_value(index)
        self.progress_slider.slider.blockSignals(False)
        self.progress_slider.update_label()
        
        try:
            # 从 model 中获取文件名
            filepath = self.model._original_files[index]
            filename = os.path.basename(filepath)
            self.filename_label_value.setText(filename)
            self.filename_label_value.setToolTip(filepath) # 完整路径作为提示
        
        except (IndexError, AttributeError) as e:
            print(f"Error updating filename: {e}")
            self.filename_label_value.setText("N/A")
            self.filename_label_value.setToolTip("")
        
        self.update_seed_status_label()
        self.canvas.load_image(index)
        # [CRITICAL FIX] 如果效果对话框是打开的，必须把新图片传给它，并强制应用当前的滑块值
        if self.effects_dialog and self.effects_dialog.isVisible():
            # 获取当前底图 (原图或去噪图)
            current_base_pixmap = self.canvas._denoised_pixmap if (self.model.show_denoised and self.canvas._denoised_pixmap) else self.canvas._original_pixmap
            
            # 更新对话框的引用图 (用于 Auto 计算)
            self.effects_dialog.set_current_pixmap(current_base_pixmap)
            
            # 强制对话框重新发射一次 preview 信号
            # 这样 ImageCanvas 就会收到 preview_effects_changed 信号，并用当前滑块的值渲染新图
            self.effects_dialog.force_preview_update()
        self.preview_panel.update_previews(index)

    @pyqtSlot(int)
    def on_files_changed(self, total_files):
        if total_files > 0:
            self.progress_slider.set_range(0, total_files - 1)
            self.on_display_mode_changed(self.model.display_mode)
            self.update_mask_source_label(self.model.load_from_save_path) #首次加载时设置标签初始状态
            self.refresh_seed_cache()
            self.on_index_changed(self.model.current_index)
        else:
            self.progress_slider.set_range(0, -1)
            self.progress_slider.clear_seed_markers()
            self.preview_panel.clear_previews()
            self.canvas.load_image(-1)
            self.seed_status_label.setText("Seed: N/A")
            self.mask_source_label.setText("来源: N/A") # 清空标签
            
            self.filename_label_value.setText("N/A")
            self.filename_label_value.setToolTip("")
            
            QMessageBox.information(self, "提示", "在指定路径下未找到图像文件。")
        self._update_navigation_controls()
    
    # --- START: 新增槽函数 ---
    @pyqtSlot(bool)
    def update_mask_source_label(self, load_from_save):
        """仅更新Mask来源标签的文本"""
        if load_from_save:
            self.mask_source_label.setText("来源: 已存 (Save)")
            self.mask_source_label.setToolTip("当前优先加载 'Save Path' (按 T 键切换)")
        else:
            self.mask_source_label.setText("来源: 二值 (Mask)")
            self.mask_source_label.setToolTip("当前优先加载 'Mask Path' (按 T 键切换)")
    
    def _clear_seed_cache(self):
        self.model.seed_manual_indices = set()
        self.model.seed_effective_indices = set()
        self.model.seed_changed_indices = set()
        self.model.seed_saved_indices = set()
        self.model.seed_auto_generated_indices = set()
        self.model.seed_mode = "none"
        self.progress_slider.clear_seed_markers()

    def refresh_seed_cache(self, updated_index=None):
        save_dir = self.model.get_path('save_path')
        original_files = getattr(self.model, '_original_files', [])
        if not save_dir or not original_files:
            self._clear_seed_cache()
            return
        if updated_index is not None and isinstance(updated_index, int):
            try:
                saved_indices = set(getattr(self.model, "seed_saved_indices", set()))
                manual_indices = set(getattr(self.model, "seed_manual_indices", set()))
                changed_indices = set(getattr(self.model, "seed_changed_indices", set()))
                auto_generated_indices = set(getattr(self.model, "seed_auto_generated_indices", set()))
                original_path = self.model._original_files[updated_index]
                frame_name = os.path.splitext(os.path.basename(original_path))[0] + ".png"
                save_path = os.path.join(save_dir, frame_name)
                mask_path = self.model._mask_files[updated_index] if updated_index < len(self.model._mask_files) else None
                if os.path.exists(to_filesystem_path(save_path)):
                    saved_indices.add(updated_index)
                else:
                    saved_indices.discard(updated_index)
                auto_generated_indices.discard(updated_index)
                source = load_grayscale(mask_path) if mask_path else None
                saved = load_grayscale(save_path)
                is_changed = False
                if source is not None and saved is not None:
                    is_changed = int((source != saved).sum()) > 0
                if not manual_indices:
                    if is_changed:
                        changed_indices.add(updated_index)
                    else:
                        changed_indices.discard(updated_index)
                if manual_indices:
                    effective_indices = set(manual_indices)
                    mode = "explicit"
                elif changed_indices:
                    effective_indices = set(changed_indices)
                    mode = "edited"
                elif saved_indices:
                    effective_indices = set(saved_indices)
                    mode = "saved"
                else:
                    effective_indices = set()
                    mode = "none"
                self.model.seed_manual_indices = manual_indices
                self.model.seed_effective_indices = effective_indices
                self.model.seed_changed_indices = changed_indices
                self.model.seed_saved_indices = saved_indices
                self.model.seed_auto_generated_indices = auto_generated_indices
                self.model.seed_mode = mode
                if getattr(self.model, "show_slider_seed_markers", True):
                    self.progress_slider.set_seed_markers(manual_indices, effective_indices)
                else:
                    self.progress_slider.clear_seed_markers()
                return
            except Exception as exc:
                print(f"[refresh_seed_cache] Incremental update failed for index {updated_index}: {exc}")
        try:
            frames = build_frame_paths(self.model._original_files, self.model._mask_files, save_dir)
            manual_indices = set(explicit_seed_indices(frames))
            effective_indices, mode = resolve_seed_indices(frames, min_changed_pixels=1)
            non_auto_saved = set(saved_frame_indices(frames))
            saved_indices = {frame.index for frame in frames if frame.has_saved_mask}
            changed_indices = set(effective_indices) if mode == "edited" else set()
        except Exception:
            self._clear_seed_cache()
            return
        self.model.seed_manual_indices = manual_indices
        self.model.seed_effective_indices = set(effective_indices)
        self.model.seed_changed_indices = changed_indices
        self.model.seed_saved_indices = saved_indices
        self.model.seed_auto_generated_indices = saved_indices - non_auto_saved
        self.model.seed_mode = mode
        if getattr(self.model, "show_slider_seed_markers", True):
            self.progress_slider.set_seed_markers(manual_indices, set(effective_indices))
        else:
            self.progress_slider.clear_seed_markers()

    def update_seed_status_label(self):
        index = self.model.current_index
        if index < 0 or not self.model._original_files:
            self.seed_status_label.setText("Seed: N/A")
            self.seed_status_label.setToolTip("当前未加载可判断的 seed 状态")
            return
        manual_indices = set(getattr(self.model, "seed_manual_indices", set()))
        effective_indices = set(getattr(self.model, "seed_effective_indices", set()))
        auto_generated_indices = set(getattr(self.model, "seed_auto_generated_indices", set()))
        saved_indices = set(getattr(self.model, "seed_saved_indices", set()))
        mode = str(getattr(self.model, "seed_mode", "none"))

        if index in manual_indices:
            self.seed_status_label.setText("Seed: 手动指定")
            self.seed_status_label.setToolTip("当前帧被手动指定为 seed，追踪和边界脚本会优先使用它。")
        elif index in effective_indices and mode == "edited":
            self.seed_status_label.setText("Seed: 自动使用")
            self.seed_status_label.setToolTip("当前帧会被脚本自动当作 seed 使用。")
        elif index in effective_indices and mode == "saved":
            self.seed_status_label.setText("Seed: 自动候选")
            self.seed_status_label.setToolTip("当前帧属于已保存候选，脚本在没有更好 seed 时会使用它。")
        elif index in auto_generated_indices:
            self.seed_status_label.setText("Seed: 自动结果")
            self.seed_status_label.setToolTip("当前帧是脚本自动生成结果，默认不会再反向作为 seed。")
        elif index in saved_indices:
            self.seed_status_label.setText("Seed: 已保存")
            self.seed_status_label.setToolTip("当前帧已保存，但不是当前生效中的 seed。")
        else:
            self.seed_status_label.setText("Seed: 否")
            self.seed_status_label.setToolTip("当前帧不是生效中的 seed。")

    def save_and_next(self):
        if self.model.current_index < 0:
            return
        if self.canvas.save_current_mask():
            self.model.increment_index()

    def load_next_binary_dataset(self):
        try:
            from Useful_script import binary_queue_next
            binary_queue_next.run(self)
        except Exception as exc:
            QMessageBox.critical(self, "切换下一个 Binary 失败", str(exc))

    def load_previous_binary_dataset(self):
        try:
            from Useful_script import binary_queue_previous
            binary_queue_previous.run(self)
        except Exception as exc:
            QMessageBox.critical(self, "切换上一个 Binary 失败", str(exc))

    def skip_current_binary_dataset(self):
        try:
            from Useful_script import binary_queue_skip
            binary_queue_skip.run(self)
        except Exception as exc:
            QMessageBox.critical(self, "跳过当前 Binary 失败", str(exc))
    
    def apply_stylesheet(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        template_path = os.path.join(script_dir, 'resources', 'style.qss.template')
        
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
            
            if self.model.config.has_section('QSS_Colors'):
                color_items = self.model.config.items('QSS_Colors')
                sorted_color_items = sorted(color_items, key=lambda item: len(item[0]), reverse=True)
                for key, value in sorted_color_items:
                    template_content = template_content.replace(f"@{key}", value)
            
            QApplication.instance().setStyleSheet(template_content)
            print("Stylesheet applied successfully.")

        except FileNotFoundError:
            print(f"Stylesheet template not found at '{template_path}', using default style.")
        except Exception as e:
            print(f"Error applying stylesheet: {e}")

    def open_settings_dialog(self):
        dialog = SettingsDialog(self.model.config, self)
        dialog.settings_applied.connect(self.apply_settings_from_dialog)
        dialog.exec()

    @pyqtSlot()
    def apply_settings_from_dialog(self):
        print("Applying settings changes from dialog...")
        self.apply_stylesheet()
        self._create_actions_and_shortcuts()
        self.canvas.update_selection_display()
        self.preview_panel.update_previews(self.model.current_index)

    def _try_restore_binary_queue_session(self):
        auto_restore = self.model.config.getboolean(
            "Scripts",
            "auto_restore_binary_queue_session",
            fallback=True,
        )
        if not auto_restore:
            return False

        try:
            from core.binary_queue_core import BinaryQueueCore
        except Exception:
            return False

        session_path = BinaryQueueCore.load_session_from_config(self)
        if not session_path:
            return False

        if not os.path.exists(to_filesystem_path(session_path)):
            BinaryQueueCore.clear_session_from_config(self)
            return False

        try:
            BinaryQueueCore.load_current_or_next_dataset(self, session_path)
            return True
        except Exception as exc:
            if "already completed" in str(exc).lower():
                return False
            QMessageBox.warning(
                self,
                "恢复 Binary 会话失败",
                f"启动时无法恢复上次 Binary 会话：\n{exc}",
            )
            return False

    def _load_initial_settings(self):
        self.apply_stylesheet()
        self.apply_seed_visual_mode(
            self.model.config.get("Preview", "seed_visual_mode", fallback="balanced"),
            persist=False,
        )
        self.original_path_selector.set_path(self.model.get_path('original_path'))
        self.denoised_path_selector.set_path(self.model.get_path('denoised_path'))
        self.mask_path_selector.set_path(self.model.get_path('mask_path'))
        save_path = self.model.get_path('save_path') or self.model.get_path('mask_path')
        self.save_path_selector.set_path(save_path)
        if self._cli_session_path and os.path.isfile(
            to_filesystem_path(self._cli_session_path)
        ):
            try:
                from core.binary_queue_core import BinaryQueueCore
                BinaryQueueCore.save_session_to_config(self, self._cli_session_path)
                BinaryQueueCore.load_current_or_next_dataset(self, self._cli_session_path)
                return
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "加载会话失败",
                    f"无法加载命令行指定的会话：\n{self._cli_session_path}\n\n{exc}",
                )
        if self._try_restore_binary_queue_session():
            return
        self.import_images()

    def load_from_manifest(self):
        """Load paths from a MagicImageJ manifest.json file."""
        from PyQt6.QtWidgets import QFileDialog, QInputDialog
        import json as _json

        manifest_path, _ = QFileDialog.getOpenFileName(
            self, "选择 manifest.json", "", "JSON (*.json)"
        )
        if not manifest_path:
            return

        try:
            with open(to_filesystem_path(manifest_path), 'r', encoding='utf-8') as f:
                manifest = _json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"无法读取 manifest.json:\n{e}")
            return

        if manifest.get("type") != "MagicImageJ_Export":
            QMessageBox.warning(self, "格式错误", "该文件不是 MagicImageJ 导出的 manifest。")
            return

        particles = manifest.get("particles", [])
        if not particles:
            QMessageBox.warning(self, "无数据", "manifest 中没有粒子数据。")
            return

        labels = [f"NP{p['id']} — {p.get('frame_range', '?')}" for p in particles]
        chosen, ok = QInputDialog.getItem(
            self, "选择粒子", "请选择要加载的粒子:", labels, 0, False
        )
        if not ok:
            return

        idx = labels.index(chosen)
        particle = particles[idx]
        paths = particle.get("paths", {})
        export_dir = os.path.dirname(to_filesystem_path(manifest_path))

        origin = os.path.join(export_dir, paths.get("origin", ""))
        mask = os.path.join(export_dir, paths.get("mask", ""))
        mask_refined = os.path.join(export_dir, paths.get("mask_refined", ""))

        if origin and os.path.isdir(origin):
            self.original_path_selector.set_path(origin)
        if mask and os.path.isdir(mask):
            self.mask_path_selector.set_path(mask)
        if mask_refined:
            os.makedirs(mask_refined, exist_ok=True)
            self.save_path_selector.set_path(mask_refined)

        contrasted = os.path.join(export_dir, paths.get("contrasted", ""))
        if contrasted and os.path.isdir(contrasted):
            self.denoised_path_selector.set_path(contrasted)

        ds = manifest.get("dataset", {})
        info = f"{ds.get('substance', '')} {ds.get('dataset_id', '')} — {particle.get('label', '')}"
        print(f"[Manifest] Loaded particle: {info}")
        self.import_images()

    def import_images(self):
        original_path = self.original_path_selector.get_path()
        save_path = self.save_path_selector.get_path()

        # 检查路径是否为空或者目录不存在
        if not original_path or not os.path.isdir(to_filesystem_path(original_path)):
            QMessageBox.warning(self, "路径错误", "“原图路径”为空或无效，可能是第一次打开没有配置，请继续。")
            # 可以选择性地弹出文件选择对话框，引导用户操作
            # self.original_path_selector.select_directory() 
            return

        if not save_path or not os.path.isdir(to_filesystem_path(save_path)):
            # 如果保存路径不存在，可以询问用户是否创建
            if save_path: # 路径不为空但目录不存在
                reply = QMessageBox.question(self, "创建目录？", f"路径 “{save_path}” 不存在。\n是否要创建它？",
                                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.Yes:
                    try:
                        os.makedirs(to_filesystem_path(save_path), exist_ok=True)
                    except Exception as e:
                        QMessageBox.critical(self, "创建失败", f"无法创建目录：{e}")
                        return
                else:
                    QMessageBox.warning(self, "路径错误", "请选择一个有效的“保存路径”！")
                    return
            else: # 路径为空
                QMessageBox.warning(self, "路径错误", "请先选择“保存路径”！")
                return
        
        self.model.update_file_lists(
            original_path,  
            self.denoised_path_selector.get_path(),  
            self.mask_path_selector.get_path()
        )

    def restore_layout(self):
        if hasattr(self, 'initial_state'):
            self.restoreState(self.initial_layout_states['main_window'])
            self.main_splitter.restoreState(self.initial_layout_states['main_splitter'])
            self.right_splitter.restoreState(self.initial_layout_states['right_splitter'])
            self.path_dock_widget.setVisible(True)

    def _safe_save_config(self):
        """Write config atomically: write to temp file, then rename to prevent corruption."""
        import tempfile
        config_path = self.model.config_path
        try:
            dir_name = os.path.dirname(config_path)
            fd, tmp_path = tempfile.mkstemp(suffix='.tmp', dir=dir_name)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as tmp_file:
                    self.model.config.write(tmp_file)
                os.replace(tmp_path, config_path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as exc:
            print(f"[Config] Atomic save failed, falling back to direct write: {exc}")
            try:
                with open(config_path, 'w', encoding='utf-8') as f:
                    self.model.config.write(f)
            except Exception as e2:
                print(f"[Config] Direct write also failed: {e2}")

    def closeEvent(self, event):
        try:
            self.model.config['Paths']['original_path'] = self.original_path_selector.get_path()
            self.model.config['Paths']['denoised_path'] = self.denoised_path_selector.get_path()
            self.model.config['Paths']['mask_path'] = self.mask_path_selector.get_path()
            self.model.config['Paths']['save_path'] = self.save_path_selector.get_path()
            self._safe_save_config()
        except Exception as e:
            print(f"关闭时保存配置文件失败: {e}")
        super().closeEvent(event)
    
    def open_effects_chooser(self):
        if self.model.current_index < 0:
            QMessageBox.warning(self, "提示", "请先加载图像。")
            return

        # 获取当前图
        current_base_pixmap = self.canvas._denoised_pixmap if (self.model.show_denoised and self.canvas._denoised_pixmap) else self.canvas._original_pixmap

        # 如果对话框还不存在，创建它
        if self.effects_dialog is None:
            self.effects_dialog = EffectsDialog(self.model, self, current_pixmap=current_base_pixmap)
            
            # 定义 Apply 回调
            def apply_new_settings(settings):
                self.canvas.push_undo_state_for_effects()
                self.model.update_effect_settings(settings)
            
            # 连接信号 (只连一次)
            self.effects_dialog.settings_applied.connect(apply_new_settings)
            self.effects_dialog.finished.connect(self.on_effects_dialog_finished)
        
        else:
            # 如果已存在，更新图片引用
            self.effects_dialog.set_current_pixmap(current_base_pixmap)
            # 恢复到上一次的正式设置 (或者保持当前状态，看需求。通常打开时应该显示当前生效的设置)
            # self.effects_dialog._load_settings_to_ui(self.model.effect_settings) 

        # 显示对话框 (非模态)
        self.effects_dialog.show()
        self.effects_dialog.raise_()
        self.effects_dialog.activateWindow()

    def on_effects_dialog_finished(self, result):
        """当效果对话框关闭时调用"""
        if result != QDialog.DialogCode.Accepted:
            # 如果是取消或关闭，恢复预览前的状态
            self.model.revert_preview_to_last_settings()
        
        # [FIXED] 不要在这里 disconnect！因为我们复用了 self.effects_dialog 实例。
        # 如果 disconnect 了，下次再打开，settings_applied 信号就断了，Apply 按钮会失效。
        pass

    # def on_effects_dialog_finished(self, result):
    #     """
    #     【新增方法】当效果对话框关闭时（通过“确定”、“取消”或“X”按钮），此槽函数被调用。
    #     """
    #     if result != QDialog.DialogCode.Accepted:
    #         self.model.revert_preview_to_last_settings()
        
    #     if self.effects_dialog:
    #         try:
    #             self.effects_dialog.disconnect()
    #         except TypeError:
    #             pass
