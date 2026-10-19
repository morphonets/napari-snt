"""Conversion of napari polyline layers to SWC text, and hand-off to SNT."""

from __future__ import annotations

import re
import tempfile
import time
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote

import numpy as np

INBOX = Path(tempfile.gettempdir()) / 'snt-napari'
SCHEME = 'snt'


def _zyx(values, pad: float) -> np.ndarray:
    """Last three entries of values as a (z, y, x) array, padded if shorter"""
    v = np.asarray(values, dtype=float)[-3:]
    return np.concatenate([np.full(3 - len(v), pad), v])


class Calibration(NamedTuple):
    """Maps napari world coordinates to SWC coordinates (um) and back.

    scale/translate describe the reference (image) layer, voxel is the voxel
    size in um. All are (z, y, x) arrays. The identity assumes that napari
    world units already are um."""

    scale: np.ndarray
    translate: np.ndarray
    voxel: np.ndarray

    def to_um(self, world: np.ndarray) -> np.ndarray:
        return (world - self.translate) / self.scale * self.voxel

    def from_um(self, um: np.ndarray) -> np.ndarray:
        """Voxel coordinates of the reference layer"""
        return um / self.voxel


IDENTITY = Calibration(np.ones(3), np.zeros(3), np.ones(3))


def make_calibration(ref_layer=None, voxel_xyz=(1.0, 1.0, 1.0)) -> Calibration:
    """Calibration for a reference layer (or None). If the layer is calibrated
    (scale other than 1) its scale is taken as the voxel size in um, otherwise
    voxel_xyz (x, y, z) is used."""
    if ref_layer is None:
        scale, translate = np.ones(3), np.zeros(3)
    else:
        scale = _zyx(ref_layer.scale, 1.0)
        translate = _zyx(ref_layer.translate, 0.0)
    if np.allclose(scale, 1.0):
        voxel = np.asarray(voxel_xyz, dtype=float)[::-1].copy()
    else:
        voxel = scale.copy()
    return Calibration(scale, translate, voxel)


def polylines(layer, calib: Calibration = IDENTITY) -> list[np.ndarray]:
    """Return the polylines of a Shapes (path/line) or Points layer as
    (N, 3) arrays of coordinates in um, (z, y, x) order."""
    name = type(layer).__name__
    if name == 'Shapes':
        raw = [
            np.asarray(d, dtype=float)
            for d, t in zip(layer.data, layer.shape_type)
            if t in ('path', 'line')
        ]
    elif name == 'Points':
        raw = [np.asarray(layer.data, dtype=float)]
    else:
        raise TypeError(f'Unsupported layer type: {name}')

    out = []
    for poly in raw:
        if len(poly) < 2:
            continue
        # NB: Layer.data_to_world() converts a single position, not an array
        # of positions (it keeps only the last ndim rows), so apply the
        # layer's scale/translate directly (rotation/shear are ignored)
        world = poly * np.asarray(layer.scale) + np.asarray(layer.translate)
        world = world[:, -3:]  # ignore any leading non-spatial axes
        if world.shape[1] == 2:  # 2D (y, x): pad z with 0
            world = np.column_stack([np.zeros(len(world)), world])
        out.append(calib.to_um(world))
    return out


def to_swc(polys: list[np.ndarray], radius: float = 0.5) -> str:
    """Serialize polylines as SWC text: one unbranched chain per polyline"""
    lines = ['# Exported from napari-snt (coordinates in um)']
    node_id = 0
    for poly in polys:
        parent = -1
        for z, y, x in poly:
            node_id += 1
            lines.append(
                f'{node_id} 0 {x:.5f} {y:.5f} {z:.5f} {radius:g} {parent}'
            )
            parent = node_id
    return '\n'.join(lines) + '\n'


def write_swc(
    layer, radius: float = 0.5, calib: Calibration = IDENTITY
) -> Path:
    """Write the layer to the shared inbox, atomically"""
    polys = polylines(layer, calib)
    if not polys:
        raise ValueError('No polylines (>= 2 points) found in the layer')
    INBOX.mkdir(parents=True, exist_ok=True)
    safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in layer.name)
    millis = time.time_ns() // 10**6 % 1000
    stamp = f"{time.strftime('%Y%m%d_%H%M%S')}_{millis:03d}"
    target = INBOX / f'{safe}_{stamp}.swc'
    tmp = target.with_suffix('.tmp')
    tmp.write_text(to_swc(polys, radius), encoding='ascii')
    tmp.replace(target)
    return target


def snt_link(swc_path: Path, mode: str = 'add') -> str:
    """snt://open link understood by SNT's link handler. mode is 'add' (keep
    paths already in SNT) or 'replace' (discard them)"""
    if mode not in ('add', 'replace'):
        raise ValueError(f'Unknown mode: {mode}')
    return (
        f'{SCHEME}://open?tracings={quote(swc_path.as_posix(), safe="")}'
        f'&mode={mode}'
    )


def read_swc(path) -> list[np.ndarray]:
    """Parse an SWC file into unbranched chains of (z, y, x) coordinates.

    A new chain starts at each root and at each child of a branch point. Chains
    starting at a branch point include it as first vertex, so that they remain
    visually connected to their parent."""
    nodes = {}  # id -> (x, y, z, parent)
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            cols = line.split()
            if len(cols) < 7:
                raise ValueError(f'Not a valid SWC line: {line[:40]}')
            nodes[int(float(cols[0]))] = (
                float(cols[2]),
                float(cols[3]),
                float(cols[4]),
                int(float(cols[6])),
            )
    children: dict[int, list[int]] = {}
    roots = []
    for nid, (_, _, _, parent) in nodes.items():
        if parent in nodes and parent != nid:
            children.setdefault(parent, []).append(nid)
        else:
            roots.append(nid)

    def zyx(nid):
        x, y, z, _ = nodes[nid]
        return [z, y, x]

    starts = list(roots)
    for nid, kids in children.items():
        if len(kids) > 1:
            starts.extend(kids)

    chains = []
    for start in starts:
        parent = nodes[start][3]
        chain = [zyx(parent)] if parent in nodes else []
        current = start
        chain.append(zyx(current))
        while len(children.get(current, ())) == 1:
            current = children[current][0]
            chain.append(zyx(current))
        if len(chain) > 1:
            chains.append(np.asarray(chain, dtype=float))
    return chains


def inbox_files() -> list[Path]:
    """SWC files (and leftover temp files) in the shared inbox"""
    if not INBOX.is_dir():
        return []
    return [
        f
        for f in INBOX.iterdir()
        if f.is_file() and f.suffix in ('.swc', '.tmp')
    ]


def clear_inbox() -> int:
    """Deletes the files listed by inbox_files(). Returns their count"""
    files = inbox_files()
    for f in files:
        f.unlink(missing_ok=True)
    return len(files)


_VOXEL_RE = re.compile(
    r'voxel separation \(x,y,z\):\s*([-+.\deE]+)\s*,\s*([-+.\deE]+)\s*,'
    r'\s*([-+.\deE]+)',
    re.IGNORECASE,
)


def swc_voxel_size(path) -> tuple[float, float, float] | None:
    """(x, y, z) voxel size in um from the header of SNT-exported SWC files,
    or None if absent"""
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            if not line.startswith('#'):
                break
            match = _VOXEL_RE.search(line)
            if match:
                try:
                    return tuple(float(v) for v in match.groups())
                except ValueError:
                    return None
    return None
