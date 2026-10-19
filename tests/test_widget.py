import numpy as np

from napari_snt import _swc
from napari_snt._swc import (
    make_calibration,
    polylines,
    read_swc,
    snt_link,
    swc_voxel_size,
    to_swc,
    write_swc,
)
from napari_snt._widget import SendToSNTWidget


def set_voxel(widget, *xyz):
    for edit, value in zip(widget.voxel_edits, xyz):
        edit.setText(str(value))
        edit.editingFinished.emit()


def test_shapes_to_swc(make_napari_viewer):
    viewer = make_napari_viewer()
    path = np.array(
        [[0, 0, 0], [1, 2, 3], [2, 4, 6], [3, 6, 9], [4, 8, 12], [5, 10, 15]],
        dtype=float,
    )
    layer = viewer.add_shapes(
        [path], shape_type='path', scale=(2, 1, 1), name='t'
    )
    polys = polylines(layer)
    assert len(polys) == 1
    assert len(polys[0]) == 6  # no vertices dropped
    assert polys[0][-1].tolist() == [10.0, 10.0, 15.0]  # z scaled by 2
    swc = to_swc(polys)
    rows = [r.split() for r in swc.splitlines() if not r.startswith('#')]
    assert [r[-1] for r in rows] == ['-1', '1', '2', '3', '4', '5']  # one chain
    assert rows[1][2:5] == ['3.00000', '2.00000', '2.00000']  # x y z
    assert len(rows) == 6


def test_points_2d_pads_z(make_napari_viewer):
    viewer = make_napari_viewer()
    layer = viewer.add_points([[0, 0], [3, 4]])
    assert polylines(layer)[0][:, 0].tolist() == [0.0, 0.0]


def test_write_and_link(make_napari_viewer):
    viewer = make_napari_viewer()
    layer = viewer.add_points([[0, 0, 0], [1, 1, 1]], name='my layer')
    swc = write_swc(layer)
    assert swc.exists() and swc.suffix == '.swc'
    assert snt_link(swc).startswith('snt://open?tracings=')
    assert snt_link(swc, fallback=True).startswith('fiji://snt/open?tracings=')


def test_widget_lists_layers(make_napari_viewer):
    viewer = make_napari_viewer()
    widget = SendToSNTWidget(viewer)
    assert not widget.send_btn.isEnabled()
    viewer.add_points([[0, 0], [1, 1]], name='pts')
    assert widget.combo.currentText() == 'pts'
    assert widget.send_btn.isEnabled() and widget.copy_btn.isEnabled()


def test_copy_link(make_napari_viewer):
    from qtpy.QtWidgets import QApplication

    viewer = make_napari_viewer()
    widget = SendToSNTWidget(viewer)
    viewer.add_points([[0, 0], [1, 1]], name='pts')
    widget._native_scheme = True
    widget.copy_link()
    assert QApplication.clipboard().text().startswith('snt://open?tracings=')
    widget._native_scheme = False
    widget.copy_link()
    assert QApplication.clipboard().text().startswith('fiji://snt/open?')


def test_copy_link_mode(make_napari_viewer):
    from qtpy.QtWidgets import QApplication

    viewer = make_napari_viewer()
    widget = SendToSNTWidget(viewer)
    viewer.add_points([[0, 0], [1, 1]], name='pts')
    widget.copy_link()
    assert QApplication.clipboard().text().endswith('&mode=add')
    widget.replace_box.setChecked(True)
    widget.copy_link()
    assert QApplication.clipboard().text().endswith('&mode=replace')


def test_scheme_registered_returns_tristate():
    from napari_snt._scheme import scheme_registered

    assert scheme_registered() in (True, False, None)


BRANCHED = """# test
1 1 0 0 0 1 -1
2 3 1 0 0 1 1
3 3 2 0 0 1 2
4 3 3 1 0 1 3
5 3 3 -1 0 1 3
6 3 4 -1 0 1 5
"""


def test_read_swc_splits_at_branches(tmp_path):
    f = tmp_path / 'b.swc'
    f.write_text(BRANCHED)
    chains = read_swc(f)
    assert [len(c) for c in chains] == [3, 2, 3]
    assert chains[0][-1].tolist() == [0.0, 0.0, 2.0]  # (z, y, x)
    assert chains[1][0].tolist() == chains[0][-1].tolist()  # joins branch


def test_import_roundtrip(make_napari_viewer, tmp_path):
    f = tmp_path / 'b.swc'
    f.write_text(BRANCHED)
    viewer = make_napari_viewer()
    widget = SendToSNTWidget(viewer)
    widget.load_swc([str(f)])
    assert viewer.layers['b'].nshapes == 3
    assert widget.combo.currentText() == 'b'


def test_clear_inbox_only_removes_bridge_files(tmp_path, monkeypatch):
    monkeypatch.setattr(_swc, 'INBOX', tmp_path)
    (tmp_path / 'a.swc').write_text('x')
    (tmp_path / 'b.tmp').write_text('x')
    (tmp_path / 'keep.txt').write_text('x')
    assert _swc.clear_inbox() == 2
    assert [f.name for f in tmp_path.iterdir()] == ['keep.txt']


def test_calibration_roundtrip_uncalibrated_image(make_napari_viewer, tmp_path):
    f = tmp_path / 'b.swc'
    f.write_text(BRANCHED)
    viewer = make_napari_viewer()
    viewer.add_image(np.zeros((4, 8, 8)), name='img')  # scale 1,1,1
    widget = SendToSNTWidget(viewer)
    set_voxel(widget, 0.5, 0.5, 2.0)  # x, y, z
    widget.load_swc([str(f)])
    layer = viewer.layers['b']
    # SWC x (um) -> voxels: 2 um / 0.5 = 4 voxels
    assert layer.data[0][-1].tolist() == [0.0, 0.0, 4.0]
    # and back to um on export
    polys = polylines(layer, widget._calibration())
    assert polys[0][-1].tolist() == [0.0, 0.0, 2.0]


def test_calibrated_image_dictates_voxel_size(make_napari_viewer):
    viewer = make_napari_viewer()
    viewer.add_image(np.zeros((4, 8, 8)), scale=(2.0, 0.5, 0.5), name='img')
    widget = SendToSNTWidget(viewer)
    assert [float(e.text()) for e in widget.voxel_edits] == [0.5, 0.5, 2.0]
    assert not any(e.isEnabled() for e in widget.voxel_edits)


def test_make_calibration_defaults():
    calib = make_calibration(None, (0.5, 0.25, 2.0))
    assert calib.voxel.tolist() == [2.0, 0.25, 0.5]  # z, y, x


def test_header_voxel_size_is_used(make_napari_viewer, tmp_path):
    f = tmp_path / 'h.swc'
    f.write_text(
        '# Voxel separation (x,y,z): 0.5, 0.5, 2.0\n' + BRANCHED
    )
    assert swc_voxel_size(f) == (0.5, 0.5, 2.0)
    viewer = make_napari_viewer()
    viewer.add_image(np.zeros((4, 8, 8)), name='img')
    widget = SendToSNTWidget(viewer)
    widget.load_swc([str(f)])
    assert [float(e.text()) for e in widget.voxel_edits] == [0.5, 0.5, 2.0]
    assert viewer.layers['h'].data[0][-1].tolist() == [0.0, 0.0, 4.0]


def test_header_voxel_size_keeps_full_precision(make_napari_viewer, tmp_path):
    f = tmp_path / 'p.swc'
    f.write_text(
        '# Voxel separation (x,y,z): 0.32964852215271034, '
        '0.32964852215271034, 0.9988\n' + BRANCHED
    )
    viewer = make_napari_viewer()
    widget = SendToSNTWidget(viewer)  # no image layer: calibration from header
    widget.load_swc([str(f)])
    assert widget._calibration().voxel[2] == 0.32964852215271034  # x
    assert widget.voxel_edits[0].text() == '0.329649'  # display is rounded
    widget.voxel_edits[0].editingFinished.emit()  # no edit: still exact
    assert widget._calibration().voxel[2] == 0.32964852215271034
    set_voxel(widget, 0.5)  # a user edit overrides it
    assert widget._calibration().voxel[2] == 0.5
    set_voxel(widget, 'abc')  # invalid input is reverted
    assert widget._calibration().voxel[2] == 0.5
    assert widget.voxel_edits[0].text() == '0.5'
