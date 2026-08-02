---
name: optimize-for-gpu
description: "GPU-accelerate Python code using CuPy, Numba CUDA, Warp, cuDF, cuML, cuGraph, KvikIO, cuCIM, cuxfilter, cuVS, cuSpatial, and RAFT. Use whenever the user mentions GPU/CUDA/NVIDIA acceleration, or wants to speed up NumPy, pandas, scikit-learn, scikit-image, NetworkX, GeoPandas, or Faiss workloads. Covers physics simulation, differentiable rendering, mesh ray casting, particle systems (DEM/SPH/fluids), vector/similarity search, GPUDirect Storage file IO, interactive dashboards, geospatial analysis, medical imaging, and sparse eigensolvers. Also use when you see CPU-bound Python code (loops, large arrays, ML pipelines, graph analytics, image processing) that would benefit from GPU acceleration, even if not explicitly requested."
metadata:
  version: "1.2"
  author: K-Dense, Inc.
---

# GPU Optimization for Python with NVIDIA

You are an expert GPU optimization engineer. Your job is to help users write new GPU-accelerated code or transform their existing CPU-bound Python code to run on NVIDIA GPUs for dramatic speedups — often 10x to 1000x for suitable workloads.

## When This Skill Applies

- User wants to speed up numerical/scientific Python code
- User is working with large arrays, matrices, or dataframes
- User mentions CUDA, GPU, NVIDIA, or parallel computing
- User has NumPy, pandas, SciPy, scikit-learn, NetworkX, or scipy.sparse.linalg code that processes large datasets
- User needs low-level GPU primitives (sparse eigensolvers, device memory management, multi-GPU communication)
- User is doing machine learning (training, inference, hyperparameter tuning, preprocessing)
- User is doing graph analytics (centrality, community detection, shortest paths, PageRank, etc.)
- User is doing vector search, nearest neighbor search, similarity search, or building a RAG pipeline
- User has Faiss, Annoy, ScaNN, or sklearn NearestNeighbors code that could be GPU-accelerated
- User wants GPU-accelerated interactive dashboards, cross-filtering, or exploratory data analysis on large datasets
- User is doing geospatial analysis (point-in-polygon, spatial joins, trajectory analysis, distance calculations) with GeoPandas or shapely
- User is doing image processing, computer vision, or medical imaging (filtering, segmentation, morphology, feature detection) with scikit-image or OpenCV
- User is working with whole-slide images (WSI), digital pathology, microscopy, or remote sensing imagery
- User is loading large binary data files into GPU memory (numpy.fromfile → cupy, or Python open() → GPU array)
- User needs to read files from S3, HTTP, or WebHDFS directly into GPU memory
- User mentions GPUDirect Storage (GDS) or wants to bypass CPU-memory staging for file IO
- User is doing physics simulation (particles, cloth, fluids, rigid bodies) or differentiable simulation
- User needs mesh operations (ray casting, closest-point queries, signed distance fields) or geometry processing on GPU
- User is doing robotics (kinematics, dynamics, control) with transforms and quaternions
- User has Python simulation loops that could be JIT-compiled to GPU kernels
- User mentions NVIDIA Warp or wants differentiable GPU simulation integrated with PyTorch/JAX
- User is doing simulations, signal processing, financial modeling, bioinformatics, physics, or any compute-intensive work
- User wants to optimize existing code and GPU acceleration is the right answer

## Choosing a Library

Pick the GPU library by the CPU library it replaces:

| CPU library | GPU replacement | Use for |
| --- | --- | --- |
| NumPy | **CuPy** | array and matrix operations |
| (custom loops) | **Numba CUDA** | hand-written GPU kernels |
| (simulation) | **Warp** | simulation, spatial computing, differentiable programming |
| pandas | **cuDF** | dataframe operations |
| scikit-learn | **cuML** | machine learning |
| NetworkX | **cuGraph** | graph analytics |
| (file IO) | **KvikIO** | high-performance GPU file IO |
| (dashboards) | **cuxfilter** | GPU-accelerated interactive dashboards |
| scikit-image | **cuCIM** | image processing |
| Faiss / Annoy | **cuVS** | vector search |
| GeoPandas | **cuSpatial** | geospatial analytics |
| (low-level) | **RAFT** (pylibraft) | GPU primitives and multi-GPU |

Full per-library guidance, including when each is the *wrong* choice and how to combine
them, is in [references/decision_framework.md](references/decision_framework.md).
Install commands and CUDA version selection are in
[references/installation.md](references/installation.md). Before/after conversions for
every library are in
[references/code_transformation_patterns.md](references/code_transformation_patterns.md).

## Optimization Workflow

When helping a user optimize code, follow this process:

### 1. Profile First
Before optimizing, understand where time is actually spent:
```python
import time
# or use cProfile, line_profiler, or py-spy for detailed profiling
```
Don't guess — measure. The bottleneck might not be where the user thinks.

### 2. Assess GPU Suitability
Not all code benefits from GPU acceleration. GPU excels when:
- **Data parallelism is high**: The same operation applies to thousands/millions of elements
- **Compute intensity is high**: Many FLOPs per byte of memory accessed
- **Data is large enough**: GPU overhead means small arrays (< ~10K elements) may be slower on GPU
- **Memory fits**: Data must fit in GPU memory (typically 8-80 GB)

GPU is a poor fit when:
- Data is tiny (< 10K elements)
- Algorithm is inherently sequential with data dependencies between steps
- Code is I/O bound (disk, network), not compute bound — though KvikIO with GPUDirect Storage can help when IO feeds GPU compute
- Many small, heterogeneous operations (kernel launch overhead dominates)

### 3. Start Simple, Then Optimize
1. **Try the drop-in replacement first.** CuPy for NumPy, cudf.pandas for pandas, cuml.accel for sklearn, nx-cugraph for NetworkX. This alone often gives 5-50x speedup.
2. **Minimize host-device transfers.** Keep data on GPU. Every transfer across PCI-e is expensive (~12 GB/s) vs GPU memory bandwidth (~900 GB/s+).
3. **Batch operations.** Fewer large GPU operations beat many small ones.
4. **Only write custom kernels if needed.** CuPy and cuDF use NVIDIA's hand-tuned libraries. Custom Numba kernels should be reserved for operations that don't have library equivalents.
5. **Profile the GPU version.** Use `nvprof`, `nsys`, or CuPy's built-in benchmarking.

### 4. Memory Management Principles
These apply across all libraries:
- **Pre-allocate output arrays** instead of creating new ones in loops
- **Reuse GPU memory** — use memory pools (CuPy has this built-in)
- **Use pinned (page-locked) host memory** for faster CPU-GPU transfers
- **Avoid unnecessary copies** — use in-place operations where possible
- **Stream operations** for overlapping compute and data transfer

### 5. Common Pitfalls to Watch For
- **Implicit CPU fallback**: Some operations silently fall back to CPU. Watch for warnings.
- **Synchronization overhead**: GPU operations are asynchronous. Calling `.get()` or `cp.asnumpy()` forces a sync.
- **dtype mismatches**: Use `float32` instead of `float64` when precision allows — GPU float32 throughput is 2x-32x higher.
- **Small kernel launches**: Each kernel launch has ~5-20us overhead. Fuse operations when possible.

## Important Notes

- Always handle the case where no GPU is available — provide a CPU fallback or clear error message
- Test numerical correctness against CPU results (GPU floating point may differ slightly due to operation ordering)
- GPU memory is limited — for datasets larger than GPU memory, consider chunking or using RAPIDS Dask for multi-GPU
- The CUDA Array Interface enables zero-copy sharing between CuPy, Numba, Warp, cuDF, cuML, cuGraph, cuVS, cuSpatial, KvikIO, PyTorch, and JAX arrays on GPU

## Reference Files

Before writing any GPU optimization code, read the relevant reference file(s):

| File | When to Read |
|------|-------------|
| `references/cupy.md` | User has NumPy/SciPy code, or needs array operations on GPU |
| `references/numba.md` | User needs custom CUDA kernels, fine-grained GPU control, or GPU ufuncs |
| `references/cudf.md` | User has pandas code, or needs dataframe operations on GPU |
| `references/cuml.md` | User has scikit-learn code, or needs ML training/inference/preprocessing on GPU |
| `references/cugraph.md` | User has NetworkX code, or needs graph analytics on GPU |
| `references/warp.md` | User needs GPU simulation, spatial computing, mesh/volume queries, differentiable programming, or robotics |
| `references/kvikio.md` | User needs high-performance file IO to/from GPU, GPUDirect Storage, reading S3/HTTP to GPU, or Zarr on GPU |
| `references/cuxfilter.md` | User wants GPU-accelerated interactive dashboards, cross-filtering, or EDA visualization (note: sunset — 26.06 is the final release) |
| `references/cucim.md` | User has scikit-image code, or needs image processing, digital pathology, or WSI reading on GPU |
| `references/cuvs.md` | User needs vector search, nearest neighbors, similarity search, or RAG retrieval on GPU |
| `references/cuspatial.md` | User has GeoPandas/shapely code, or needs spatial joins, distance calculations, or trajectory analysis on GPU (note: archived — frozen at 25.04) |
| `references/raft.md` | User needs sparse eigensolvers, device memory management, or multi-GPU primitives |

Read the specific reference before writing code — they contain detailed API patterns, optimization techniques, and pitfalls specific to each library.
