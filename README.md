# napari-snt

[![License GNU GPL v3.0](https://img.shields.io/pypi/l/napari-snt.svg?color=green)](https://github.com/morphonets/napari-snt/raw/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/napari-snt.svg?color=green)](https://pypi.org/project/napari-snt)
[![Python Version](https://img.shields.io/pypi/pyversions/napari-snt.svg?color=green)](https://python.org)
[![tests](https://github.com/morphonets/napari-snt/workflows/tests/badge.svg)](https://github.com/morphonets/napari-snt/actions)
[![codecov](https://codecov.io/gh/morphonets/napari-snt/branch/main/graph/badge.svg)](https://codecov.io/gh/morphonets/napari-snt)
[![napari hub](https://img.shields.io/endpoint?url=https://api.napari-hub.org/shields/napari-snt)](https://napari-hub.org/plugins/napari-snt)
[![npe2](https://img.shields.io/badge/plugin-npe2-blue?link=https://napari.org/stable/plugins/index.html)](https://napari.org/stable/plugins/index.html)
[![Copier](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/copier-org/copier/master/img/badge/badge-grayscale-inverted-border-purple.json)](https://github.com/copier-org/copier)

Send napari polylines to [SNT](https://github.com/morphonets/snt) via snt:// links
and receive SNT's SWC data as napari polylines.

------------------------------------------------------------------------------------

This [napari] plugin was generated with [copier] using the [napari-plugin-template].


## Usage

1. Draw polylines in a Shapes layer (path or line shapes), or place ordered
   points in a Points layer.
2. Open *Plugins > SNT Bridge (napari-snt)*, pick the layer and click
   *Open in SNT* (or *Copy snt:// Link*).

The plugin writes an SWC file to `<tempdir>/snt-napari/` (one unbranched chain
per polyline, coordinates in µm, see Calibration below) and opens
`snt://open?tracings=<path>`. SNT must be installed in Fiji with its `snt://`
link handler registered. If the link cannot be opened, the SWC is still on
disk and can be opened in SNT manually.

SWC coordinates are expected in µm. The *Calibration* section picks the image
layer to align with: if it carries a scale, that is used as voxel size.
If it is uncalibrated, enter the voxel size in the x/y/z fields, which
is applied when importing (µm to voxels) and when sending (voxels to µm).
SWC files exported by SNT state their voxel size in the header, which is
detected automatically on import.

*Import SWC...* does the reverse: it loads SWC files (e.g., exported from SNT)
as a Shapes layer with one path per unbranched segment, in (z, y, x) order, so
that they can be sent back to SNT.

> [!TIP]
> In napari's 2D view, a 3D path is only drawn on the slices it crosses. If
> imported paths seem to be missing, check the 3D view or scroll through z.

*Open Folder* shows the bridge folder, *Clear Data* deletes the exported SWC
files in it (after confirmation), and *Help* opens this page.

## Installation

From napari: Plugins > Install/Uninstall Plugins..., scroll to the bottom of
the plugin manager window to find the manual installation text box and type:

```
git+https://github.com/morphonets/napari-snt
```

From the command line:

```bash
pip install git+https://github.com/morphonets/napari-snt
```

Once released on PyPI, `pip install napari-snt` will also work.

## License

GNU GPL v3.0

[napari]: https://github.com/napari/napari
[copier]: https://copier.readthedocs.io/en/stable/
[napari-plugin-template]: https://github.com/napari/napari-plugin-template
