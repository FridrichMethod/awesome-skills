# Installation

Per-library install commands, CUDA version selection, and environment setup.

## Installation

IMPORTANT: Always use `uv add` for package installation — never `pip install` or `conda install`. This applies to install instructions in code comments, docstrings, error messages, and any other output you generate. If the user's project uses a different package manager, follow their lead, but default to `uv add`.

RAPIDS packages below track RAPIDS 26.06 (June 2026): they require Python >= 3.11 and CUDA 12.x or 13.x. Every RAPIDS package ships `-cu12` and `-cu13` wheel variants (except the archived cuSpatial) — the examples use `-cu12`; substitute `-cu13` for CUDA 13 systems. Most RAPIDS wheels are now published directly on PyPI; only cuGraph, nx-cugraph, and cuSpatial still require the NVIDIA index.

```bash
# CuPy (choose the right CUDA version; CuPy 14+ supports CUDA 12/13 only)
uv add cupy-cuda12x          # For CUDA 12.x
uv add cupy-cuda13x          # For CUDA 13.x

# Numba with CUDA support (installs numba automatically)
uv add "numba-cuda[cu12]"    # or [cu13] — the NVIDIA package providing the numba.cuda target

# Warp (simulation, spatial computing, differentiable programming)
uv add warp-lang              # CUDA 12 runtime included; CUDA 13 builds are on GitHub Releases only

# cuDF (RAPIDS)
uv add cudf-cu12
# For cudf.pandas accelerator mode, that's all you need
# Load it with: python -m cudf.pandas your_script.py

# cuML (RAPIDS machine learning)
uv add cuml-cu12
# For cuml.accel accelerator mode (zero-change sklearn acceleration):
# Load it with: python -m cuml.accel your_script.py

# cuGraph (RAPIDS graph analytics) — NVIDIA index still required (PyPI has only stub packages)
uv add --extra-index-url=https://pypi.nvidia.com cugraph-cu12    # Core cuGraph
uv add --extra-index-url=https://pypi.nvidia.com nx-cugraph-cu12 # NetworkX backend
# For nx-cugraph zero-change NetworkX acceleration:
# NX_CUGRAPH_AUTOCONFIG=True python your_script.py

# KvikIO (high-performance GPU file IO)
uv add kvikio-cu12
# Optional: uv add zarr          # For Zarr GPU backend support

# cuxfilter (interactive dashboards) — SUNSET: 26.06 is the final release
uv add cuxfilter-cu12
# Depends on cuDF — installs it automatically

# cuCIM (RAPIDS image processing — scikit-image on GPU)
uv add cucim-cu12

# cuVS (RAPIDS vector search)
uv add cuvs-cu12

# cuSpatial (geospatial) — ARCHIVED: frozen at 25.04, pins cudf-cu12==25.4.*
# Install only in a dedicated environment; NVIDIA index required
uv add --extra-index-url=https://pypi.nvidia.com cuspatial-cu12

# RAFT (low-level GPU primitives)
uv add pylibraft-cu12   # Core primitives
uv add raft-dask-cu12   # Multi-GPU support (optional)
```

To check CUDA availability after installation:

```python
# CuPy
import cupy as cp
print(cp.cuda.runtime.getDeviceCount())  # Should be >= 1

# Numba
from numba import cuda
print(cuda.is_available())               # Should be True
print(cuda.detect())                     # Shows GPU details

# cuDF
import cudf
print(cudf.Series([1, 2, 3]))           # Should print a GPU series

# cuML
import cuml
print(cuml.__version__)                  # Should print version

# cuGraph
import cugraph
print(cugraph.__version__)               # Should print version

# Warp
import warp as wp
wp.init()                                # Should print device info

# KvikIO
import kvikio
import kvikio.cufile_driver
print(kvikio.cufile_driver.get("is_gds_available"))  # True if GDS is set up

# cuxfilter
import cuxfilter
print(cuxfilter.__version__)             # Should print version

# cuVS
from cuvs.neighbors import cagra
import cupy as cp
dataset = cp.random.rand(1000, 128, dtype=cp.float32)
index = cagra.build(cagra.IndexParams(), dataset)
print("cuVS working")                    # Should print confirmation

# cuSpatial
import cuspatial
from shapely.geometry import Point
gs = cuspatial.GeoSeries([Point(0, 0)])
print("cuSpatial working")              # Should print confirmation

# RAFT (pylibraft)
from pylibraft.common import DeviceResources
handle = DeviceResources()
handle.sync()
print("pylibraft is working")
```
