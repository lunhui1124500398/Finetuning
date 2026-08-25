# -*- coding: utf-8 -*-
"""镜像填充重推 —— 把排除区域填掉后重跑推理, 再把区域内的预测删干净。

用途: 模型抓住漂移黑角/液池边界而漏掉真粒子时。事后删连通分量救不了这种帧
(locator 已经被带偏, 真粒子根本没进视野), 必须在推理前把黑边从输入里消掉。

三段跨环境流水线见 core/repair_runner.py 的模块注释。
"""

import os
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

import cv2
import numpy as np

from core import repair_runner as rr
from core.exclusion_region import (
    apply_auto_black_settings, effective_region_mask, load_region_config,
)
from core.mirror_fill import mirror_fill
from core.repair_adopt import (
    STATUS_MANUAL, AdoptError, apply_adoption, plan_adoption, summarize_plan,
)

SCRIPT_NAME = "镜像填充重推..."
SCRIPT_DESCRIPTION = "把排除区域镜像填充后重跑 IVAN+分割, 再删掉区域内的预测。永不覆盖已有结果。"
SCRIPT_ORDER = 50
# 用 SCRIPT_CATEGORY 逃生舱, 免得去改 script_loader 里那个硬编码 stem 集合
SCRIPT_CATEGORY = "Mask 处理"


# ----------------------------------------------------------------------
# 数据集定位
# ----------------------------------------------------------------------

def resolve_context(model):
    """从 save_path 反推 Exports 目录和粒子名。

    约定布局: <Exports>/_masks/<particle>_mask_refined
    """
    save_dir = model.get_path("save_path")
    if not save_dir:
        raise ValueError("没有设置保存路径。请先加载数据集。")
    save_path = Path(save_dir)
    name = save_path.name
    for suffix in ("_mask_refined", "_mask_new", "_mask"):
        if name.endswith(suffix):
            particle = name[: -len(suffix)]
            break
    else:
        particle = name

    exports = save_path.parent
    if exports.name == "_masks":
        exports = exports.parent
    return exports, particle, save_path


# ----------------------------------------------------------------------
# 填充预览
# ----------------------------------------------------------------------

class PreviewDialog(QDialog):
    """原图 / 填充后 并排。秒级可见, 区域画错不必等三段推理跑完才发现。"""

    def __init__(self, original, filled, region, parent=None):
        super().__init__(parent)
        self.setWindowTitle("镜像填充预览")
        layout = QVBoxLayout(self)

        info = QLabel(
            f"排除区覆盖 {int((region > 0).sum())} 像素 "
            f"({(region > 0).mean() * 100:.1f}% 的画面)。\n"
            "右图区域内的内容已被邻域反射填充，硬边界消失；区域外一个像素都没动。"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        images = QHBoxLayout()
        for title, array in (("原图", original), ("镜像填充后", filled)):
            column = QVBoxLayout()
            caption = QLabel(title)
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            view = QLabel()
            view.setPixmap(self._to_pixmap(array))
            view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(caption)
            column.addWidget(view)
            images.addLayout(column)
        layout.addLayout(images)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    @staticmethod
    def _to_pixmap(array, target=320):
        array = np.ascontiguousarray(array)
        if array.ndim == 3:
            array = cv2.cvtColor(array, cv2.COLOR_BGR2GRAY)
        if array.dtype != np.uint8:
            array = cv2.normalize(array, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        height, width = array.shape
        scale = max(1, target // max(height, width))
        big = cv2.resize(array, (width * scale, height * scale), interpolation=cv2.INTER_NEAREST)
        from PyQt6.QtGui import QImage
        image = QImage(big.data, big.shape[1], big.shape[0], big.strides[0],
                       QImage.Format.Format_Grayscale8)
        return QPixmap.fromImage(image.copy())


# ----------------------------------------------------------------------
# 运行进度
# ----------------------------------------------------------------------

class RunDialog(QDialog):
    """三段流水线的进度 + 实时日志。

    用 processEvents 泵事件而不是开线程 —— 与本仓其它脚本一致, 且子进程输出本来
    就是逐行回调进来的, 没有阻塞点。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("镜像填充重推")
        self.setMinimumSize(760, 480)
        self.cancelled = False

        layout = QVBoxLayout(self)
        self.stage_label = QLabel("准备中...")
        self.stage_label.setStyleSheet("font-weight: 600; font-size: 14px;")
        self.progress = QProgressBar()
        self.progress.setRange(0, 4)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.rejected.connect(self._cancel)

        layout.addWidget(self.stage_label)
        layout.addWidget(self.progress)
        layout.addWidget(self.log)
        layout.addWidget(self.buttons)

    def _cancel(self):
        self.cancelled = True
        self.stage_label.setText("正在取消... (当前子进程跑完这一步才会停)")

    def set_stage(self, index, text):
        self.progress.setValue(index)
        self.stage_label.setText(text)
        self.append(f"\n=== {text} ===")

    def append(self, line):
        self.log.appendPlainText(line)
        QApplication.processEvents()

    def finish(self, ok):
        self.buttons.setStandardButtons(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.disconnect()
        self.buttons.rejected.connect(self.accept)
        self.buttons.accepted.connect(self.accept)
        self.stage_label.setText("完成" if ok else "失败 —— 详见上方日志")
        if ok:
            self.progress.setValue(self.progress.maximum())


# ----------------------------------------------------------------------
# 采纳
# ----------------------------------------------------------------------

class AdoptDialog(QDialog):
    """逐帧决定要不要采纳。**人工帧默认不勾。**"""

    def __init__(self, items, version, parent=None):
        super().__init__(parent)
        self.items = items
        self.setWindowTitle(f"采纳 v{version} 的重推结果")
        self.setMinimumSize(620, 480)

        summary = summarize_plan(items)
        layout = QVBoxLayout(self)

        header = QLabel(
            f"共 {summary['total']} 帧：默认采纳 {len(summary['default_adopt'])} 帧，"
            f"保护 {len(summary['protected'])} 帧。\n"
            "已人工精修的帧默认不勾选 —— 判定依据是 sha1 重新哈希比对，"
            "所以“自动生成后又被你手改过”的帧同样会被认成人工。\n"
            "采纳只写 _mask_refined/，第一次推理的 _mask/ 永久保留作对照。"
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        self.table = QTableWidget(len(items), 3)
        self.table.setHorizontalHeaderLabels(["采纳", "帧", "当前状态"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for row, item in enumerate(items):
            box = QCheckBox()
            box.setChecked(not item.protected)
            box.setEnabled(item.adoptable)
            holder = QHBoxLayout()
            holder.addWidget(box)
            holder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            holder.setContentsMargins(0, 0, 0, 0)
            wrapper = QLabel()
            wrapper.setLayout(holder)
            self.table.setCellWidget(row, 0, wrapper)
            self.table.setItem(row, 1, QTableWidgetItem(item.frame_name))
            status = QTableWidgetItem(item.label)
            if item.status == STATUS_MANUAL:
                status.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, 2, status)
            box.setProperty("frame_name", item.frame_name)
            self._boxes = getattr(self, "_boxes", [])
            self._boxes.append(box)
        layout.addWidget(self.table)

        row = QHBoxLayout()
        select_default = QPushButton("只选默认可采纳的")
        select_all = QPushButton("全选 (含人工帧)")
        select_none = QPushButton("全不选")
        select_default.clicked.connect(lambda: self._set_all(mode="default"))
        select_all.clicked.connect(lambda: self._set_all(mode="all"))
        select_none.clicked.connect(lambda: self._set_all(mode="none"))
        row.addWidget(select_default)
        row.addWidget(select_all)
        row.addWidget(select_none)
        row.addStretch()
        layout.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("采纳选中帧")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_all(self, mode):
        for box, item in zip(self._boxes, self.items):
            if not item.adoptable:
                continue
            if mode == "all":
                box.setChecked(True)
            elif mode == "none":
                box.setChecked(False)
            else:
                box.setChecked(not item.protected)

    def selected_names(self):
        return [b.property("frame_name") for b in self._boxes if b.isChecked() and b.isEnabled()]

    def has_manual_override(self):
        chosen = set(self.selected_names())
        return [i.frame_name for i in self.items
                if i.status == STATUS_MANUAL and i.frame_name in chosen]


# ----------------------------------------------------------------------
# 主面板
# ----------------------------------------------------------------------

class MirrorRepairDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.model = main_window.model
        self.exports, self.particle, self.save_dir = resolve_context(self.model)
        self.last_layout = None

        self.setWindowTitle("镜像填充重推")
        self.setMinimumWidth(560)

        total = len(self.model._original_files)
        layout = QVBoxLayout(self)

        context = QLabel(
            f"数据集：<b>{self.particle}</b>　共 {total} 帧<br>"
            f"输出目录：{rr.repair_root_for(self.exports, self.particle)}"
        )
        context.setWordWrap(True)
        layout.addWidget(context)

        # --- 区域 ---
        region_group = QGroupBox("① 排除区域")
        region_form = QFormLayout(region_group)
        self.region_status = QLabel()
        self.region_status.setWordWrap(True)
        region_form.addRow(self.region_status)
        hint = QLabel(
            "区域在主画布上按 <b>G</b>（区域模式）绘制，红/黄反向蚂蚁线即区域。"
            "生效区域 = 手动区域 ∪ 自动黑边，逐帧取并集。"
        )
        hint.setWordWrap(True)
        region_form.addRow(hint)

        # 自动黑边控件。参数写回 _exclusion_region.json, 重推时逐帧生效。
        auto_row = QHBoxLayout()
        self.auto_black_check = QCheckBox("自动检测黑边")
        self.auto_black_check.setToolTip(
            "逐帧检测漂移矫正留下的纯黑 padding，与手动区域取并集。\n"
            "只抓触碰画面边界的暗块，粒子内部的暗区不会被误吞。"
        )
        self.auto_threshold_spin = QSpinBox()
        self.auto_threshold_spin.setRange(0, 255)
        self.auto_threshold_spin.setToolTip(
            "像素值 ≤ 此阈值算作黑边。\n"
            "⚠ contrasted 图像经过对比度拉伸，纯黑 padding 可能不再是 0 —— "
            "若自动检测抓不到东西，把阈值调高（可先看该数据集的像素地板）。"
        )
        self.auto_dilate_spin = QSpinBox()
        self.auto_dilate_spin.setRange(0, 50)
        self.auto_dilate_spin.setToolTip("向外膨胀的余量，盖住黑边与有效区之间的抗锯齿过渡带。")
        auto_row.addWidget(self.auto_black_check)
        auto_row.addSpacing(12)
        auto_row.addWidget(QLabel("阈值"))
        auto_row.addWidget(self.auto_threshold_spin)
        auto_row.addSpacing(8)
        auto_row.addWidget(QLabel("余量"))
        auto_row.addWidget(self.auto_dilate_spin)
        auto_row.addWidget(QLabel("px"))
        auto_row.addStretch()
        region_form.addRow(auto_row)

        # 从配置填初值; blockSignals 防止填值时触发写回
        auto = self.region_config().auto_black
        for widget, value in (
            (self.auto_black_check, auto.enabled),
            (self.auto_threshold_spin, auto.threshold),
            (self.auto_dilate_spin, auto.dilate),
        ):
            widget.blockSignals(True)
            (widget.setChecked if isinstance(widget, QCheckBox) else widget.setValue)(value)
            widget.blockSignals(False)
        self.auto_threshold_spin.setEnabled(auto.enabled)
        self.auto_dilate_spin.setEnabled(auto.enabled)

        self.auto_black_check.toggled.connect(self._on_auto_black_changed)
        self.auto_threshold_spin.valueChanged.connect(self._on_auto_black_changed)
        self.auto_dilate_spin.valueChanged.connect(self._on_auto_black_changed)

        layout.addWidget(region_group)

        # --- 参数 ---
        param_group = QGroupBox("② 参数")
        param_form = QFormLayout(param_group)
        self.start_spin = QSpinBox()
        self.start_spin.setRange(1, max(1, total))
        self.start_spin.setValue(1)
        self.end_spin = QSpinBox()
        self.end_spin.setRange(1, max(1, total))
        self.end_spin.setValue(max(1, total))
        range_row = QHBoxLayout()
        range_row.addWidget(self.start_spin)
        range_row.addWidget(QLabel("到"))
        range_row.addWidget(self.end_spin)
        param_form.addRow("帧范围", range_row)

        # 填充方式 + 方向。默认定向倒映 + 自动方向。
        self.method_combo = QComboBox()
        for label, key in (("定向倒映（推荐）", "directional"),
                           ("各向距离反射", "distance"),
                           ("inpaint 平滑填充", "inpaint")):
            self.method_combo.addItem(label, key)
        self.method_combo.setToolTip(
            "定向倒映：沿单一方向整体翻折（底部黑边→垂直把上方内容倒下来），纹理连续无接缝。\n"
            "各向距离反射：任意形状通用，但矩形等形状会出现对角接缝。\n"
            "inpaint：邻域插值最平滑、对分割最安全，但大区域会糊、丢纹理。"
        )
        self.direction_combo = QComboBox()
        for label, key in (("自动", "auto"), ("垂直（上下翻）", "vertical"),
                           ("水平（左右翻）", "horizontal")):
            self.direction_combo.addItem(label, key)
        self.direction_combo.setToolTip(
            "定向倒映的翻折方向。自动 = 按黑边形状判断（横条→垂直，竖条→水平，"
            "对角/方块→退回各向反射）。"
        )
        method_row = QHBoxLayout()
        method_row.addWidget(self.method_combo)
        method_row.addWidget(QLabel("方向"))
        method_row.addWidget(self.direction_combo)
        method_row.addStretch()
        param_form.addRow("填充方式", method_row)
        self.method_combo.currentIndexChanged.connect(self._on_method_changed)
        self._on_method_changed()

        self.feather_spin = QDoubleSpinBox()
        self.feather_spin.setRange(0.0, 10.0)
        self.feather_spin.setSingleStep(0.5)
        self.feather_spin.setValue(0.0)
        self.feather_spin.setToolTip(
            "对填充内容做轻微高斯平滑，压掉反射接缝的高频。\n"
            "只作用于区域内部，区域外一个像素都不动。0 = 不平滑。"
        )
        param_form.addRow("羽化", self.feather_spin)

        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.05, 0.95)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setValue(0.50)
        param_form.addRow("分割阈值", self.threshold_spin)
        layout.addWidget(param_group)

        # --- 动作 ---
        action_group = QGroupBox("③ 执行")
        action_layout = QVBoxLayout(action_group)
        self.preview_button = QPushButton("① 预览当前帧的镜像填充（秒级）")
        self.preview_button.setToolTip("先看填充效果，区域画错不必等三段推理跑完才发现")
        self.run_button = QPushButton("② 一键重推（镜像填充 → IVAN 去噪 → 分割 → 按区域裁剪）")
        self.adopt_button = QPushButton("③ 采纳：把结果复制进 _mask_refined/ ...")
        self.adopt_button.setToolTip(
            "把这个版本的重推结果逐帧复制进 _mask_refined/。\n"
            "会先检测每帧是否已有内容：已人工精修的帧默认跳过，覆盖前另有确认。\n"
            "第一次推理的 _mask/ 永久保留作对照。"
        )
        self.adopt_button.setEnabled(False)
        self.preview_button.clicked.connect(self.on_preview)
        self.run_button.clicked.connect(self.on_run)
        self.adopt_button.clicked.connect(self.on_adopt)
        for button in (self.preview_button, self.run_button, self.adopt_button):
            button.setMinimumHeight(34)
            action_layout.addWidget(button)
        layout.addWidget(action_group)

        self.version_label = QLabel()
        self.version_label.setWordWrap(True)
        layout.addWidget(self.version_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.refresh_status()

    # ------------------------------------------------------------------
    def region_config(self):
        return load_region_config(str(self.save_dir))

    def _on_method_changed(self, *_):
        # 方向下拉只在"定向倒映"时有意义
        self.direction_combo.setEnabled(self.method_combo.currentData() == "directional")

    def _fill_kwargs(self):
        return dict(
            feather=self.feather_spin.value(),
            method=self.method_combo.currentData(),
            direction=self.direction_combo.currentData(),
        )

    def _on_auto_black_changed(self, *_):
        enabled = self.auto_black_check.isChecked()
        self.auto_threshold_spin.setEnabled(enabled)
        self.auto_dilate_spin.setEnabled(enabled)
        apply_auto_black_settings(
            str(self.save_dir),
            enabled=enabled,
            threshold=self.auto_threshold_spin.value(),
            dilate=self.auto_dilate_spin.value(),
        )
        self.refresh_status()

    def refresh_status(self):
        config = self.region_config()
        manual_count = sum(len(r.polygons) for r in config.manual)
        if manual_count:
            ranges = ", ".join(f"{r.start + 1}-{r.end + 1}" for r in config.manual)
            text = f"手动区域 {manual_count} 块（帧范围 {ranges}）"
        else:
            text = "<span style='color:#b91c1c'>尚未绘制手动区域（可只靠下方自动黑边）</span>"
        self.region_status.setText(text)

        versions = rr.existing_versions(self.exports, self.particle)
        if versions:
            self.version_label.setText(
                f"已有修复版本：{', '.join('v' + str(v) for v in versions)}　"
                "（每次重推都写进新版本，旧版本永不被覆盖）"
            )
        else:
            self.version_label.setText("尚无修复版本。")

    def selected_frames(self):
        start = self.start_spin.value() - 1
        end = self.end_spin.value() - 1
        if start > end:
            raise ValueError("起始帧不能大于结束帧。")
        paths = self.model._original_files[start:end + 1]
        indices = list(range(start, end + 1))
        return paths, indices

    # ------------------------------------------------------------------
    def on_preview(self):
        index = self.model.current_index
        if index < 0:
            QMessageBox.warning(self, "没有当前帧", "请先选中一帧。")
            return
        path = self.model._original_files[index]
        image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if image is None:
            QMessageBox.warning(self, "读不出图像", path)
            return

        config = self.region_config()
        region = effective_region_mask(config, index, image)
        if not region.any():
            QMessageBox.information(
                self, "这一帧没有排除区域",
                "当前帧上手动区域和自动黑边都是空的，填充无事可做。\n\n"
                "请在主画布按 G 进入区域模式画出要排除的部分；"
                "若指望自动检测黑边，注意 contrasted 图像可能已被对比度拉伸，"
                "纯黑 padding 不再是 0 —— 可把阈值调高后再试。",
            )
            return

        filled = mirror_fill(image, region, **self._fill_kwargs())
        PreviewDialog(image, filled, region, parent=self).exec()

    # ------------------------------------------------------------------
    def on_run(self):
        try:
            paths, indices = self.selected_frames()
        except ValueError as exc:
            QMessageBox.warning(self, "范围错误", str(exc))
            return
        if not paths:
            QMessageBox.warning(self, "没有帧", "选中的范围里没有任何帧。")
            return

        config = self.region_config()
        confirm = QMessageBox.question(
            self, "确认重推",
            f"将对 {len(paths)} 帧执行：\n"
            f"　① 镜像填充\n　② IVAN 去噪（GPU）\n　③ 分割\n　④ 按区域裁剪\n\n"
            f"结果写进新版本目录，现有的 _mask/ 和 _mask_refined/ 不会被改动。\n"
            f"采纳是之后一个单独的步骤。\n\n继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        dialog = RunDialog(self)
        dialog.show()
        QApplication.processEvents()

        try:
            layout = rr.allocate_repair_version(self.exports, self.particle)
            self.last_layout = layout
            dialog.append(f"版本目录: {layout.root}")

            # 把区域配置一并存进版本目录, 这次修复用的是什么区域将来查得到
            import shutil as _shutil
            region_src = self.save_dir / "_exclusion_region.json"
            if region_src.exists():
                _shutil.copyfile(region_src, layout.region_json)

            def pump(current, total, message):
                dialog.append(f"[{current + 1}/{total}] {message}")
                return not dialog.cancelled

            dialog.set_stage(0, "① 镜像填充")
            report = rr.prepare_padded_frames(
                paths, indices, layout, config,
                progress_callback=pump, **self._fill_kwargs(),
            )
            dialog.append(f"填充 {report['count']} 帧。")
            if report["empty_region_frames"]:
                dialog.append(
                    f"⚠ 有 {len(report['empty_region_frames'])} 帧的排除区域为空, "
                    f"这些帧等于原样重推: {report['empty_region_frames'][:20]}"
                )

            dialog.set_stage(1, "② IVAN 去噪 (GPU)")
            result = rr.run_command(rr.build_ivan_command(layout),
                                    on_line=dialog.append, log_path=layout.log_path)
            if result["returncode"] != 0:
                raise rr.RepairError(f"IVAN 去噪失败 (退出码 {result['returncode']})。详见日志。")
            if result["errors"]:
                # IVAN 单图失败只打 [ERROR] 不改退出码
                raise rr.RepairError(
                    "IVAN 报了错误行（退出码仍是 0，必须靠这里拦住）:\n"
                    + "\n".join(result["errors"][:8])
                )
            rr.promote_ivan_output(layout)

            dialog.set_stage(2, "③ 分割")
            dialog.append("先跑 --dry-run 确认分割器看得见这批数据...")
            probe = rr.run_command(rr.build_seg_command(layout, dry_run=True),
                                   log_path=layout.log_path)
            info = rr.parse_dry_run(probe["stdout"])
            dialog.append(f"发现结果: n_sequences={info.get('n_sequences')} "
                          f"n_discovery_issues={info.get('n_discovery_issues')}")
            rr.assert_discovery_ok(info)

            result = rr.run_command(
                rr.build_seg_command(layout, threshold=self.threshold_spin.value()),
                on_line=dialog.append, log_path=layout.log_path,
            )
            if result["returncode"] != 0:
                raise rr.RepairError(f"分割失败 (退出码 {result['returncode']})。详见日志。")
            written = rr.parse_result_line(result["stdout"])
            dialog.append(f"分割结果: {written}")
            mask_dir = rr.find_mask_output_dir(layout)

            dialog.set_stage(3, "④ 按区域裁掉区域内的预测")
            stats = rr.crop_masks_by_region(mask_dir, paths, indices, config,
                                            layout.result_dir, progress_callback=pump)
            dialog.append(
                f"裁剪 {stats['processed']} 帧，抹掉 {stats['removed_pixels']} 个前景像素"
                + (f"，缺失 {stats['missing']} 帧" if stats["missing"] else "")
            )

            dialog.append(f"\n✔ 完成。结果在: {layout.result_dir}")
            dialog.append(
                "下一步：关掉此窗口 → 点「③ 采纳」把结果复制进 _mask_refined/。\n"
                "采纳会逐帧检测、跳过你手工精修过的帧，覆盖前还会再确认一次。"
            )
            dialog.finish(True)
            self.adopt_button.setEnabled(True)
            self.refresh_status()
        except Exception as exc:
            dialog.append(f"\n!!! {exc}")
            dialog.finish(False)
            QMessageBox.critical(self, "重推失败", str(exc))
            return

        dialog.exec()

    # ------------------------------------------------------------------
    def on_adopt(self):
        layout = self.last_layout
        if layout is None:
            versions = rr.existing_versions(self.exports, self.particle)
            if not versions:
                QMessageBox.information(self, "还没有结果", "请先跑一次重推。")
                return
            layout = rr.RepairLayout(
                root=rr.repair_root_for(self.exports, self.particle) / f"v{versions[-1]}",
                version=versions[-1], particle=self.particle,
            )

        names = sorted(p.name for p in layout.result_dir.glob("*.png"))
        if not names:
            QMessageBox.information(self, "没有可采纳的结果", f"{layout.result_dir} 是空的。")
            return

        try:
            items = plan_adoption(layout.result_dir, self.save_dir, names)
        except AdoptError as exc:
            QMessageBox.critical(self, "拒绝采纳", str(exc))
            return

        dialog = AdoptDialog(items, layout.version, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        overrides = dialog.has_manual_override()
        if overrides:
            confirm = QMessageBox.warning(
                self, "将覆盖人工精修的帧",
                f"以下 {len(overrides)} 帧是你手工精修过的，采纳会覆盖它们：\n\n"
                + "、".join(overrides[:30]) + ("..." if len(overrides) > 30 else "")
                + "\n\n确定继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        stats = apply_adoption(items, selected=dialog.selected_names(),
                               method=f"repair_v{layout.version}")

        if self.model.current_index >= 0:
            self.main_window.canvas.load_image(self.model.current_index)
            self.main_window.preview_panel.update_previews(self.model.current_index)
        for hook in ("refresh_seed_cache", "update_seed_status_label"):
            if hasattr(self.main_window, hook):
                getattr(self.main_window, hook)()

        QMessageBox.information(
            self, "采纳完成",
            f"写入 {stats['written_count']} 帧\n"
            f"跳过 {stats['skipped_count']} 帧\n"
            + (f"其中覆盖人工帧 {len(stats['overwritten_manual'])} 帧\n"
               if stats["overwritten_manual"] else "")
            + f"\n第一次推理的 _mask/ 与 v{layout.version} 的结果都原样保留。",
        )


def run(main_window):
    try:
        MirrorRepairDialog(main_window).exec()
    except ValueError as exc:
        QMessageBox.warning(main_window, "无法启动", str(exc))
