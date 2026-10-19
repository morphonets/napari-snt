"""Dock widget: send a napari polyline layer to SNT through an snt:// link"""

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from qtpy.QtCore import QUrl
from qtpy.QtGui import QDesktopServices
from qtpy.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ._scheme import scheme_registered
from ._swc import (
    FEATURE_ID,
    FEATURE_PARENT,
    INBOX,
    clear_inbox,
    inbox_files,
    make_calibration,
    read_swc_tree,
    snt_link,
    swc_voxel_size,
    write_swc,
)

if TYPE_CHECKING:
    import napari

_SUPPORTED = ('Shapes', 'Points')
_HELP_URL = 'https://github.com/morphonets/napari-snt#readme'


class SendToSNTWidget(QWidget):
    def __init__(self, viewer: 'napari.viewer.Viewer'):
        super().__init__()
        self.viewer = viewer

        self.combo = QComboBox()
        self.ref_combo = QComboBox()
        for combo in (self.combo, self.ref_combo):
            # Do not let long layer names widen the whole widget
            policy = QComboBox.SizeAdjustPolicy
            combo.setSizeAdjustPolicy(
                policy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(12)
        self._voxel = [1.0, 1.0, 1.0]  # x, y, z (um); full precision
        self.voxel_edits = []  # x, y, z (um per voxel)
        for axis in 'xyz':
            edit = QLineEdit('1')
            edit.setPlaceholderText(axis)
            edit.setToolTip(f'{axis} voxel size (um)')
            edit.setMinimumWidth(30)
            # Ignore the (wide) default size hint: keeps the widget narrow
            edit.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
            )
            edit.editingFinished.connect(self._on_voxel_edited)
            self.voxel_edits.append(edit)
        self.send_btn = QPushButton('Open in SNT')
        self.copy_btn = QPushButton('Copy snt:// Link')
        self._native_scheme = False
        self._hierarchy_report = {}
        self.replace_box = QCheckBox('Replace in SNT')
        self.replace_box.setToolTip(
            'Discard paths already in SNT instead of adding to them '
            '(SNT asks for confirmation if they are unsaved)'
        )
        self.import_btn = QPushButton('Import SWC...')
        self.reveal_btn = QPushButton('Open Folder')
        self.clear_btn = QPushButton('Clear Data')
        self.help_btn = QPushButton('Help')
        self.status = QLabel('')
        self.status.setWordWrap(True)
        self.status.setStyleSheet('color: gray;')

        buttons_out = QGridLayout()
        buttons_out.addWidget(self.send_btn, 0, 0)
        buttons_out.addWidget(self.copy_btn, 0, 1)
        buttons_out.addWidget(self.replace_box, 1, 0, 1, 2)
        buttons_in = QGridLayout()
        buttons_in.addWidget(self.import_btn, 0, 0)
        buttons_misc = QGridLayout()
        buttons_misc.addWidget(self.reveal_btn, 0, 0)
        buttons_misc.addWidget(self.clear_btn, 0, 1)
        buttons_misc.addWidget(self.help_btn, 0, 2)

        layout = QVBoxLayout()
        layout.addWidget(QLabel('Calibration (Send and Receive):'))
        calib = QGridLayout()
        calib.addWidget(QLabel('From image:'), 0, 0)
        calib.addWidget(self.ref_combo, 0, 1, 1, 3)  # spans the 3 fields
        calib.addWidget(QLabel('Voxel (x,y,z):'), 1, 0)
        for i, edit in enumerate(self.voxel_edits):
            calib.addWidget(edit, 1, i + 1)
        for col in (1, 2, 3):
            calib.setColumnStretch(col, 1)  # equal-width fields
        layout.addLayout(calib)

        layout.addSpacing(10)
        layout.addWidget(QLabel('Send (Shapes or Points layer):'))
        layout.addWidget(self.combo)
        layout.addLayout(buttons_out)
        layout.addWidget(QLabel('Receive:'))
        layout.addLayout(buttons_in)
        layout.addSpacing(10)
        layout.addWidget(QLabel('Bridge Utilities:'))
        layout.addLayout(buttons_misc)
        layout.addWidget(QLabel('Status:'))
        layout.addWidget(self.status)
        layout.addStretch()
        self.setLayout(layout)

        self.ref_combo.currentIndexChanged.connect(self._sync_voxel_fields)
        self.send_btn.clicked.connect(self.send)
        self.copy_btn.clicked.connect(self.copy_link)
        self.import_btn.clicked.connect(self.import_swc)
        self.reveal_btn.clicked.connect(self.reveal)
        self.clear_btn.clicked.connect(self.clear_data)
        self.help_btn.clicked.connect(self.show_help)
        for ev in ('inserted', 'removed', 'reordered'):
            getattr(self.viewer.layers.events, ev).connect(self._refresh)
        self._refresh()
        self._startup_status()

    def _startup_status(self):
        # Empty when the OS cannot tell us (None)
        registered = scheme_registered()
        # snt:// only if known to be registered, otherwise fiji://snt/
        self._native_scheme = registered is True
        if registered is True:
            self._info('Bridge available')
        elif registered is False:
            self._info('snt:// is not registered in your system: using fiji://')

    def _refresh(self, *_):
        current = self.combo.currentText()
        self.combo.clear()
        names = [
            lyr.name
            for lyr in self.viewer.layers
            if type(lyr).__name__ in _SUPPORTED
        ]
        self.combo.addItems(names)
        if current in names:
            self.combo.setCurrentText(current)
        for btn in (self.send_btn, self.copy_btn):
            btn.setEnabled(bool(names))
        self._refresh_references()

    def _refresh_references(self):
        current = self.ref_combo.currentText()
        self.ref_combo.blockSignals(True)
        self.ref_combo.clear()
        self.ref_combo.addItem('(none)')  # no reference image
        images = [
            lyr.name
            for lyr in self.viewer.layers
            if type(lyr).__name__ == 'Image'
        ]
        self.ref_combo.addItems(images)
        if current in images:
            self.ref_combo.setCurrentText(current)
        elif images:
            self.ref_combo.setCurrentIndex(1)
        self.ref_combo.blockSignals(False)
        self._sync_voxel_fields()

    def _ref_layer(self):
        name = self.ref_combo.currentText()
        if name and name != '(none)' and name in self.viewer.layers:
            return self.viewer.layers[name]
        return None

    def _ref_is_calibrated(self) -> bool:
        ref = self._ref_layer()
        return ref is not None and not np.allclose(ref.scale, 1.0)

    def _sync_voxel_fields(self, *_):
        """Calibrated reference layers dictate the voxel size"""
        calibrated = self._ref_is_calibrated()
        if calibrated:
            scale = np.asarray(self._ref_layer().scale, dtype=float)
            self._set_voxel_size(scale[-3:][::-1])
        for edit in self.voxel_edits:
            edit.setEnabled(not calibrated)

    @staticmethod
    def _fmt(value: float) -> str:
        return f'{value:.6g}'

    def _set_voxel_size(self, xyz):
        """Stores xyz at full precision. The fields display it rounded"""
        self._voxel = [float(v) for v in xyz]
        for edit, value in zip(self.voxel_edits, self._voxel):
            edit.setText(self._fmt(value))
            edit.setToolTip(f'{value:.10g} um')

    def _on_voxel_edited(self):
        values = list(self._voxel)
        for i, edit in enumerate(self.voxel_edits):
            text = edit.text().strip().replace(',', '.')
            if text == self._fmt(values[i]):
                continue  # unchanged: keep full precision
            try:
                value = float(text)
                if not value > 0:
                    raise ValueError
            except ValueError:
                self._error(f'Invalid voxel size: "{edit.text()}"')
                values_text = self._fmt(self._voxel[i])
                edit.setText(values_text)
                continue
            values[i] = value
        self._voxel = values

    def _calibration(self):
        return make_calibration(self._ref_layer(), self._voxel)

    def _info(self, msg: str):
        self.status.setStyleSheet('color: gray;')
        self.status.setText(msg)

    def _error(self, msg: str):
        self.status.setStyleSheet('color: #c0392b;')
        self.status.setText(msg)

    def _export(self):
        """Writes the selected layer to the inbox. Returns (swc, link)"""
        name = self.combo.currentText()
        if not name:
            return None, None
        try:
            report = {}
            swc = write_swc(
                self.viewer.layers[name],
                calib=self._calibration(),
                report=report,
            )
        except (TypeError, ValueError, OSError) as err:
            self._error(f'Error: {err}')
            return None, None
        mode = 'replace' if self.replace_box.isChecked() else 'add'
        self._hierarchy_report = report
        return swc, snt_link(swc, mode, fallback=not self._native_scheme)

    def _repairs(self) -> str:
        """Note on paths whose hierarchy could not be preserved"""
        rep = self._hierarchy_report
        parts = []
        if rep.get('reassigned'):
            parts.append(f"{rep['reassigned']} new or duplicated")
        if rep.get('orphaned'):
            parts.append(f"{rep['orphaned']} orphaned")
        if not parts:
            return ''
        return ' - exported as roots: ' + ' and '.join(parts)

    def send(self):
        swc, link = self._export()
        if link is None:
            return
        if QDesktopServices.openUrl(QUrl(link)):
            self._info(f'Opened in SNT: {swc.name}{self._repairs()}')
        else:
            self._error(
                'Could not open the link (is the snt:// scheme registered in '
                f'your system?). SWC saved as {swc.name}'
            )

    def copy_link(self):
        swc, link = self._export()
        if link is None:
            return
        QApplication.clipboard().setText(link)
        self._info(f'Link copied to clipboard ({swc.name}){self._repairs()}')

    def import_swc(self):
        start = str(INBOX) if INBOX.is_dir() else str(Path.home())
        files, _ = QFileDialog.getOpenFileNames(
            self, 'Import SWC', start, 'SWC files (*.swc);;All files (*)'
        )
        if files:
            self.load_swc(files)

    def load_swc(self, files):
        """Adds one Shapes (path) layer per SWC file"""
        loaded = []
        for f in files:
            try:
                header_voxel = swc_voxel_size(f)
                if header_voxel and not self._ref_is_calibrated():
                    # SNT-exported SWCs state their voxel size
                    self._set_voxel_size(header_voxel)
                calib = self._calibration()
                chains, parents = read_swc_tree(f)
                if not chains:
                    raise ValueError('no paths found')
            except (ValueError, OSError) as err:
                self._error(f'Could not import {Path(f).name}: {err}')
                continue
            layer = self.viewer.add_shapes(
                [calib.from_um(c) for c in chains],
                features={
                    FEATURE_ID: list(range(1, len(chains) + 1)),
                    FEATURE_PARENT: [p + 1 if p >= 0 else -1 for p in parents],
                },
                scale=calib.scale,
                translate=calib.translate,
                shape_type='path',
                name=Path(f).stem,
                edge_color='cyan',
                edge_width=1,
            )
            try:  # new paths: unassigned id and no parent
                layer.feature_defaults = {FEATURE_ID: 0, FEATURE_PARENT: -1}
            except (ValueError, KeyError, TypeError):
                pass
            loaded.append(f'{Path(f).name} ({len(chains)} paths)')
        if loaded:
            self._info('Imported ' + ', '.join(loaded))

    def reveal(self):
        try:
            INBOX.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            self._error(f'Error: {err}')
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(INBOX))):
            self._error(f'Could not open {INBOX}')

    def clear_data(self):
        n = len(inbox_files())
        if not n:
            self._info('Nothing to clear')
            return
        buttons = QMessageBox.StandardButton
        answer = QMessageBox.question(
            self,
            'Clear Bridge Data',
            f'Delete {n} exported SWC file(s) from\n{INBOX}?',
            buttons.Yes | buttons.No,
            buttons.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._info(f'Deleted {clear_inbox()} file(s)')
        except OSError as err:
            self._error(f'Error: {err}')

    def show_help(self):
        QDesktopServices.openUrl(QUrl(_HELP_URL))
