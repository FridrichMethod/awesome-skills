---
name: "rdkit-chemdraw-cdxml"
description: "Read, write, and edit ChemDraw CDX/CDXML files with RDKit's rdkit.Chem.rdChemDraw plus direct XML editing, always paired with a rendered PNG. Parse molecules and reactions from .cdxml/.cdx, write structures with good 2D depiction, and hand-build or modify the parts RDKit cannot write: reaction arrows, plus signs, schemes/steps, and text/labels. Use for reaction schemes, synthesis routes, mechanisms, retrosynthesis, or SI figures. Critical: RDKit writes structures only — round-tripping a reaction through a Mol silently drops arrows and text; this skill shows the XML layer that preserves them. For pure molecular analysis (descriptors, fingerprints, SMARTS) use rdkit-cheminformatics; for multi-format 3D conversion use openbabel."
license: "BSD-3-Clause"
---

# RDKit ChemDraw / CDXML Toolkit

## Overview

CDXML is an XML serialization of ChemDraw's object tree (CDX is its binary form). RDKit 2022.09+ exposes an optional Revvity ChemDraw parser at `rdkit.Chem.rdChemDraw` that reads molecules **and** reactions and writes molecule structures. RDKit cannot write **arrows, plus signs, schemes, or text** — those are built or edited at the XML level. This skill covers the full read → depict → annotate → write → modify → render loop.

## Output contract

A `.cdxml` is not viewable without ChemDraw, and **you cannot run ChemDraw here** — so the rendered PNG is the only evidence the file is correct. Therefore:

- **Deliver `<name>.cdxml` and `<name>.png` together, matching basenames** — never the CDXML alone. `build_scheme()` and Module 9 write both; the helper raises if the PNG cannot be produced.
- **Validate before delivering** with `scripts/check_scheme.py` (rebuilds each molecule from the drawing, sanitizes, checks mass balance across arrows, and critiques layout). Drive it to zero problems.
- **Report honestly**: "opens correctly in ChemDraw" is never something you tested; stereochemistry is not drawn unless you added it. Offer a plain SMILES list of intermediates for schemes with more than three structures.

## When to Use

- Convert SMILES/SDF/Mol into `.cdxml` files that open cleanly in ChemDraw
- Extract molecules or reactions (reactants/agents/products) from `.cdxml` or `.cdx`
- Build a reaction scheme: fragments + arrows + `+` separators + conditions text
- Modify an existing ChemDraw file (relabel, annotate, reposition) without losing its arrows/text
- Batch-generate ChemDraw figures for a reaction dataset or SAR table
- Use `rdkit-cheminformatics` instead for descriptors/fingerprints/SMARTS with no ChemDraw I/O
- For multi-format 3D conversion (MOL2, XYZ, PDB), use `openbabel`; this toolkit is 2D ChemDraw-specific

## Prerequisites

- **Python packages**: `rdkit` (2023.03+, built with ChemDraw support), `epam.indigo` (renders CDXML→PNG); `xml.etree.ElementTree` (stdlib) handles all XML editing.
- **Inputs**: SMILES/Mol for writing; `.cdxml` (UTF-8 text) or `.cdx` (binary) for reading.
- **Check before installing.** RDKit is usually already present — run `python -c "import rdkit"` first; inside pixi use `pixi run python ...`.
- **Install `epam.indigo` into the interpreter that runs your code.** A bare `pip install` can land in a different Python than the kernel (e.g. system `/usr/local` vs the pixi env that has rdkit), so `import indigo` still fails even though the install "succeeded" — and no single interpreter then has both rdkit and indigo. In a Jupyter/IPython kernel use `%pip install epam.indigo`; otherwise `python -m pip install epam.indigo` (the running interpreter), or add it to the project env (`pixi add epam.indigo`). For the same reason, **do not run the build/render in a fresh `subprocess`** (`["python", …]` may resolve yet another interpreter) — import the helper and run it in the current process.

```bash
python -m pip install epam.indigo   # the running interpreter; or  %pip install epam.indigo  in Jupyter
python -c "from rdkit import Chem; print('ChemDraw write support:', Chem.HasChemDrawCDXSupport())"
```

## Quick Start

```python
from rdkit import Chem
from rdkit.Chem import rdChemDraw, rdDepictor

mol = Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O")   # aspirin
rdDepictor.SetPreferCoordGen(True)
rdDepictor.Compute2DCoords(mol)                      # coordinates are REQUIRED before writing
cdxml = rdChemDraw.MolToChemDrawBlock(mol, rdChemDraw.CDXFormat.CDXML)   # -> str
open("aspirin.cdxml", "w", encoding="utf-8").write(cdxml)
```

## Core API

### Module 1: Reading molecules

`MolsFromChemDrawFile` / `MolsFromChemDrawBlock` handle both `.cdx` and `.cdxml`, returning a tuple of `Mol` (one per fragment).

```python
from rdkit import Chem
from rdkit.Chem import rdChemDraw

mols = rdChemDraw.MolsFromChemDrawFile("drawing.cdxml", sanitize=True, removeHs=True)
for m in mols:
    print(Chem.MolToSmiles(m))

block = open("drawing.cdxml", encoding="utf-8").read()
mols = rdChemDraw.MolsFromChemDrawBlock(block, sanitize=True, removeHs=True)
mols_legacy = Chem.MolsFromCDXML(block)   # CDXML-only fallback, no ChemDraw SDK needed
```

### Module 2: Reading reactions (arrows → reactant/product split)

`ReactionsFromChemDrawBlock` interprets `<step>`/`<arrow>` and returns `ChemicalReaction`s with reactants, agents, and products split out. Note the reaction reader defaults `sanitize=False`.

```python
from rdkit import Chem
from rdkit.Chem import rdChemDraw, rdChemReactions

block = open("reaction.cdxml", encoding="utf-8").read()
for rxn in rdChemDraw.ReactionsFromChemDrawBlock(block, sanitize=True):
    print("reactants:", [Chem.MolToSmiles(m) for m in rxn.GetReactants()])
    print("products :", [Chem.MolToSmiles(m) for m in rxn.GetProducts()])

rxns = rdChemReactions.ReactionsFromCDXMLBlock(block, sanitize=True)   # legacy equivalent
```

### Module 3: Writing molecule structures

`MolToChemDrawBlock` writes one molecule to CDXML (`str`). CDX (binary) write is broken in `rdChemDraw` (`UnicodeDecodeError`); use the legacy writer for CDX bytes.

```python
from rdkit import Chem
from rdkit.Chem import rdChemDraw, rdDepictor, rdmolfiles

mol = Chem.MolFromSmiles("c1ccccc1O")
rdDepictor.Compute2DCoords(mol)                                          # coords first, always
cdxml = rdChemDraw.MolToChemDrawBlock(mol, rdChemDraw.CDXFormat.CDXML)   # str (preferred)
cdx_bytes = Chem.MolToCDXMLBlock(mol, rdmolfiles.CDXMLFormat.CDX)        # bytes (legacy writer)
```

### Module 4: Good molecular depiction

Layout quality is set *before* writing. CoordGen gives more natural coordinates; template alignment keeps a shared scaffold oriented consistently across a series. Note: CoordGen still tangles cages and bridged bicyclics — check those in the render.

```python
from rdkit import Chem
from rdkit.Chem import rdDepictor

rdDepictor.SetPreferCoordGen(True)
mol = Chem.MolFromSmiles("O=C(Nc1ccc(cc1)S(=O)(=O)N)C")
rdDepictor.Compute2DCoords(mol)
rdDepictor.StraightenDepiction(mol)
rdDepictor.NormalizeDepiction(mol)      # uniform median bond length
```

```python
# Align a series to a shared scaffold so the core is drawn identically each time
template = Chem.MolFromSmiles("c1ccc(cc1)S(=O)(=O)N")
rdDepictor.Compute2DCoords(template)
for m in [Chem.MolFromSmiles(s) for s in ["Cc1ccc(cc1)S(=O)(=O)N", "Clc1ccc(cc1)S(=O)(=O)N"]]:
    rdDepictor.GenerateDepictionMatching2DStructure(m, template)
```

### Module 5: Drawing arrows

A reaction arrow is an `<arrow>` with `Head3D`/`Tail3D` (`"x y z"`, y increases downward). `ArrowheadHead`/`ArrowheadType` style the head. Equilibrium/resonance/retrosynthetic arrows use a `<graphic>` Line with `ArrowType`.

```python
import xml.etree.ElementTree as ET

def make_arrow(arrow_id, tail_xy, head_xy):
    (tx, ty), (hx, hy) = tail_xy, head_xy
    return ET.Element("arrow", {
        "id": str(arrow_id), "FillType": "None", "ArrowheadType": "Solid",
        "ArrowheadHead": "Full", "HeadSize": "2250",
        "BoundingBox": f"{min(tx,hx)} {min(ty,hy)-4} {max(tx,hx)} {max(ty,hy)+4}",
        "Head3D": f"{hx} {hy} 0", "Tail3D": f"{tx} {ty} 0"})

print(ET.tostring(make_arrow(40, (160, 100), (210, 100)), encoding="unicode"))
equil = ET.Element("graphic", {"id": "41", "GraphicType": "Line",
                               "ArrowType": "Equilibrium", "BoundingBox": "160 100 210 100"})
```

### Module 6: Reaction schemes and steps

A `<scheme>` groups `<step>` objects that reference page objects **by id**: `ReactionStepReactants`, `ReactionStepProducts`, `ReactionStepArrows`, `ReactionStepPlusses`, and objects above/below the arrow.

```python
import xml.etree.ElementTree as ET

def make_plus(gid, x, y):
    return ET.Element("graphic", {"id": str(gid), "GraphicType": "Symbol",
                                  "SymbolType": "Plus", "BoundingBox": f"{x} {y-7} {x+15} {y+8}"})

scheme = ET.Element("scheme", {"id": "60"})
ET.SubElement(scheme, "step", {"id": "61", "ReactionStepReactants": "10 20",
    "ReactionStepProducts": "50", "ReactionStepArrows": "40",
    "ReactionStepPlusses": "30", "ReactionStepObjectsAboveArrow": "70"})
print(ET.tostring(scheme, encoding="unicode"))
```

### Module 7: Adding text and labels

Free text is a `<t>` at `p="x y"` holding one or more `<s>` styled-string children. `<s>` references a `font` id (`<fonttable>`) and `color` index (`<colortable>`); `face` is a bitmask (1=bold, 2=italic, 32=subscript, 64=superscript). Split a `<t>` into multiple `<s>` runs for subscripts (`Br₂`, `CO₂H`). Indigo renders **subscript (32) but not superscript (64)** — it drops the run's leading text — so keep charges inline (`H+`, `OH-`). `°C` (temperatures) and `Δ` (heat) render with the Arial font; avoid other non-Latin-1 characters (`hν`, en-dashes).

```python
import xml.etree.ElementTree as ET

def make_text(tid, x, y, runs, font_id=21, size=10):
    """runs: list of (text, face). face 0=normal, 1=bold, 32=subscript, 64=superscript."""
    t = ET.Element("t", {"id": str(tid), "p": f"{x} {y}"})
    for text, face in runs:
        ET.SubElement(t, "s", {"font": str(font_id), "size": str(size),
                               "color": "0", "face": str(face)}).text = text
    return t

print(ET.tostring(make_text(70, 175, 92, [("reflux, 2 h", 0)]), encoding="unicode"))
print(ET.tostring(make_text(80, 158, 135, [("Br", 0), ("2", 32), (" (excess)", 0)]),
                  encoding="unicode"))   # Br<sub>2</sub> (excess)
```

### Module 8: Editing an existing CDXML file

`ElementTree` round-trips arrows, text, and graphics it does not understand, so you can edit a real ChemDraw file without losing objects — unlike an RDKit Mol round-trip.

```python
import xml.etree.ElementTree as ET

tree = ET.parse("reaction.cdxml")          # DOCTYPE is dropped on re-save (harmless)
root = tree.getroot()
for s in root.iter("s"):                   # relabel "Cl" -> "Br"
    if s.text == "Cl":
        s.text = "Br"
cap = ET.SubElement(root.find("page"), "t", {"p": "100 300"})
ET.SubElement(cap, "s", {"font": "21", "size": "12", "color": "0"}).text = "Scheme 1"
tree.write("reaction_edited.cdxml", encoding="unicode", xml_declaration=True)
```

### Module 9: Rendering CDXML to PNG

Render the PNG next to the CDXML (same basename), look at it, then deliver both. [Indigo](https://lifescience.opensource.epam.com/indigo/) (`epam.indigo`) loads a CDXML — a scheme with arrows as a *reaction*, a lone structure as a *molecule* — and rasterizes arrows, text, and layout faithfully. (RDKit's own `Draw.ReactionToImage` re-lays-out molecules and drops the ChemDraw arrows/text, so use Indigo to render a file as authored.)

```python
from pathlib import Path
from indigo import Indigo
from indigo.renderer import IndigoRenderer

def render_cdxml(cdxml_path, png_path=None, width=1600):
    png_path = png_path or str(Path(cdxml_path).with_suffix(".png"))
    ind = Indigo(); rnd = IndigoRenderer(ind)
    ind.setOption("render-output-format", "png")
    ind.setOption("render-background-color", "1,1,1")
    ind.setOption("render-image-width", width)
    cdxml = open(cdxml_path, encoding="utf-8").read()
    try:
        obj = ind.loadReaction(cdxml)   # scheme with arrows
    except Exception:
        obj = ind.loadMolecule(cdxml)   # single structure
    rnd.renderToFile(obj, png_path)
    return png_path

print("Wrote", render_cdxml("scheme.cdxml"))
```

## Key Concepts

### CDXML coordinate system

**y increases downward** (origin top-left). Atoms: `p="x y"`; arrows: `Head3D`/`Tail3D="x y z"`; graphics/text: `BoundingBox="x1 y1 x2 y2"`. Default bond length ≈ 30.

```python
def shift_fragment(frag, dx, dy):      # move a fragment onto the canvas
    for n in frag.iter("n"):
        x, y = map(float, n.get("p").split())
        n.set("p", f"{x+dx} {y+dy}")
    return frag
```

### Object-id reference model

Every object has a unique integer `id`; reactions and groups reference members **by id**, not by nesting. When merging fragments from separate RDKit outputs (each starts ids at 1), renumber all ids to stay globally unique, then wire `<step>` to the new ids.

### RDKit vs XML capability boundary

| Task | RDKit `rdChemDraw` | Direct XML |
|------|--------------------|-----------|
| Read molecules / reactions | ✅ | — |
| Write molecule structure | ✅ (CDXML) | — |
| Write arrows / plus / scheme / text | ❌ | ✅ |
| Preserve objects while editing | ❌ (drops on Mol round-trip) | ✅ |

## Common Workflows

### Workflow 1: SMILES → single-molecule CDXML

```python
from rdkit import Chem
from rdkit.Chem import rdChemDraw, rdDepictor

def smiles_to_cdxml(smiles, path):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles}")
    rdDepictor.SetPreferCoordGen(True)
    rdDepictor.Compute2DCoords(mol)
    rdDepictor.StraightenDepiction(mol)
    open(path, "w", encoding="utf-8").write(rdChemDraw.MolToChemDrawBlock(mol))
    return path

print("Wrote", smiles_to_cdxml("CC(=O)Oc1ccccc1C(=O)O", "aspirin.cdxml"))
```

### Workflow 2: Hand-assemble a reaction from Modules 5-7

Combine `_fragment_of` (write a mol, extract `<fragment>`, renumber ids, shift x) with an arrow, a plus, conditions text, and a `<step>`. Render with Module 9. For multi-step schemes prefer Workflow 4.

```python
from rdkit import Chem
from rdkit.Chem import rdChemDraw, rdDepictor, rdChemReactions
import xml.etree.ElementTree as ET

def _fragment_of(smiles, base_id, dx):
    m = Chem.MolFromSmiles(smiles); rdDepictor.Compute2DCoords(m)
    frag = ET.fromstring(rdChemDraw.MolToChemDrawBlock(m)).find("page/fragment")
    remap = {}
    for i, el in enumerate([frag, *frag.iter("n"), *frag.iter("b")]):
        remap[el.get("id")] = str(base_id + i); el.set("id", remap[el.get("id")])
    for b in frag.iter("b"):
        b.set("B", remap[b.get("B")]); b.set("E", remap[b.get("E")])
    for n in frag.iter("n"):
        x, y = map(float, n.get("p").split()); n.set("p", f"{x+dx} {y}")
    return frag

root = ET.Element("CDXML", {"BondLength": "30"}); page = ET.SubElement(root, "page")
page.append(_fragment_of("CCO", 100, 0))
ET.SubElement(page, "graphic", {"id": "30", "GraphicType": "Symbol",
                                "SymbolType": "Plus", "BoundingBox": "60 -7 75 8"})
page.append(_fragment_of("CC(=O)O", 200, 120))
ET.SubElement(page, "arrow", {"id": "40", "FillType": "None", "ArrowheadHead": "Full",
    "ArrowheadType": "Solid", "HeadSize": "2250", "Head3D": "320 3 0", "Tail3D": "260 3 0"})
cond = ET.SubElement(page, "t", {"id": "70", "p": "270 -12"})
ET.SubElement(cond, "s", {"font": "21", "size": "9", "color": "0"}).text = "H+, reflux"
page.append(_fragment_of("CCOC(C)=O", 300, 420))
scheme = ET.SubElement(page, "scheme", {"id": "60"})
ET.SubElement(scheme, "step", {"id": "61", "ReactionStepReactants": "100 200",
    "ReactionStepProducts": "300", "ReactionStepArrows": "40", "ReactionStepPlusses": "30"})
ET.SubElement(ET.SubElement(root, "fonttable"), "font",
              {"id": "21", "charset": "x-mac-roman", "name": "Helvetica"})

cdxml = ET.tostring(root, encoding="unicode")
open("esterification.cdxml", "w", encoding="utf-8").write(cdxml)
print("reactions re-parsed:", len(rdChemReactions.ReactionsFromCDXMLBlock(cdxml, sanitize=True)))
```

### Workflow 3: Edit an existing file, preserving arrows and text

```python
import xml.etree.ElementTree as ET

tree = ET.parse("input_reaction.cdxml"); root = tree.getroot()
title = ET.SubElement(root.find("page"), "t", {"p": "50 -30"})
ET.SubElement(title, "s", {"font": "21", "size": "14", "color": "0", "face": "1"}).text = "Route A"
for arrow in root.iter("arrow"):
    arrow.set("HeadSize", "3000")
tree.write("output_reaction.cdxml", encoding="unicode", xml_declaration=True)
```

### Workflow 4: Multi-step scheme with the bundled helper (recommended)

`scripts/build_reaction_scheme.py` turns `(smiles, name, conditions)` steps into a laid-out scheme **and its PNG in one call**, handling grid layout, globally unique ids, single arrows, and conditions text placed clear of structures — the defects that recur when schemes are hand-built. Cells auto-size to the largest structure, so big molecules never overlap. Model convergent/multi-component steps by folding co-reactants into `conditions` (e.g. `["+ (MeO2C)2C=CHOMe", "Base, MeCN"]`), keeping one main-chain structure per cell.

**Copy the scripts into your working directory with your file tools — not from Python.** Inside the execution sandbox the `/SciAgent-Skills/...` path is reachable **only through your read-file tool**; it is not on the sandbox filesystem, so a Python `open()` or `import` of that path fails with `FileNotFoundError`/`ModuleNotFoundError`. For each of `build_reaction_scheme.py` and `check_scheme.py` (each is self-contained — rdkit + epam.indigo only — copy just what you need):

1. **Read-file tool** on `/SciAgent-Skills/skills/structural-biology-drug-discovery/rdkit-chemdraw-cdxml/scripts/<name>` (the leading slash routes to the skills backend) → returns the script text.
2. **Write-file tool** → save it to `./<name>` in the working directory.

Then import the local copies. (Importing writes a harmless `__pycache__/`; set `PYTHONDONTWRITEBYTECODE=1` to suppress it.)

```python
from build_reaction_scheme import build_scheme    # local copies, already in the workdir
from check_scheme import check_all

steps = [
    {"smiles": "O=C1CCCC1", "name": "cyclopentanone"},
    {"smiles": "O=C1C(Br)C(Br)C(Br)C1Br", "name": "tetrabromoketone",
     "conditions": ["Br2 (excess)", "AcOH, 25 C"]},          # reagents for the arrow into this step
    {"smiles": "O=C1C=CC=C1Br", "name": "2-bromocyclopentadienone",
     "conditions": ["Et2NH", "cold Et2O"]},
    {"smiles": "C12C3C4C1C5C2C3C45", "name": "cubane", "conditions": ["(remaining steps)"]},
]
cdxml, png = build_scheme(steps, "cubane.cdxml", title="Total Synthesis of Cubane", cols=4)
check_all("cubane.cdxml", expect={3: "C12C3C4C1C5C2C3C45"})   # validate before delivering
print(f"Deliverables: {cdxml} + {png}")
```

## Key Parameters

| Parameter | Module / Function | Default | Options | Effect |
|-----------|-------------------|---------|---------|--------|
| `format` | `MolToChemDrawBlock` | `CDXFormat.CDXML` | `CDXML`, `CDX` | Use CDXML (str); for CDX bytes use legacy `MolToCDXMLBlock` |
| `sanitize` | `MolsFromChemDrawBlock` | `True` | `True`/`False` | `False` to inspect raw/invalid input |
| `sanitize` | `ReactionsFromChemDrawBlock` | `False` | `True`/`False` | Defaults **False** — pass `True` for clean SMILES |
| `SetPreferCoordGen` | `rdDepictor` | `False` | `True`/`False` | `True` gives more natural 2D layouts |
| `ArrowheadHead` | `<arrow>` XML | — | `Full`, `HalfLeft`, `HalfRight`, `None` | Arrowhead style |
| `ArrowType` | `<graphic>` Line | — | `FullHead`, `Equilibrium`, `Resonance`, `RetroSynthetic`, `NoGo` | Special arrow semantics |
| `BondLength` | `<CDXML>` root | `""` (RDKit) | numeric, e.g. `30` | Canvas scale; set a number so structures/arrows scale together |

## Best Practices

1. **Compute 2D coordinates before writing** (`SetPreferCoordGen(True)` then `Compute2DCoords`); a molecule without coordinates writes as a degenerate layout.
2. **Never round-trip a reaction through a Mol if you need the drawing** — reading drops arrows, plus signs, text, and graphics. Edit reaction files on the XML tree (Module 8).
3. **Keep object ids globally unique.** Merging RDKit outputs (each starts at 1) collides and breaks `<step>` references and doubles arrows; renumber into disjoint blocks.
4. **Prefer CDXML (text) over CDX (binary).** CDX write via `rdChemDraw` raises `UnicodeDecodeError`; only legacy `Chem.MolToCDXMLBlock(mol, CDXMLFormat.CDX)` returns valid CDX bytes.
5. **Write a complete document header** — `<CDXML BondLength=...>` plus a standard `<fonttable>`/`<colortable>` and page dimensions. See `references/cdxml-schema-reference.md`.
6. **Text**: use `°C` for temperatures and `Δ` for heat (both render); keep charges inline (`H+`, `OH-`) since Indigo has no superscript; avoid other non-Latin-1 characters. Render heteroatoms via `<n Element=...>`, not free `<t>` text; don't add decorative flags ("Chiral"/"racemic") — use wedge bonds. Keep labels clear of the arrow line: names under the structure, conditions offset above/beside the arrow. (`build_scheme` does all of this — `0 C`→`0 °C`, `heat`→`Δ`, subscripts, spacing — automatically.)
7. **Deliver the CDXML and PNG together, and run `check_scheme.check_all` first.** The render and the critic catch overlaps, duplicate/degenerate arrows, dropped intermediates, and connectivity errors before the user sees them.

## Common Recipes

### Recipe: Batch SMILES → CDXML files

```python
from rdkit import Chem
from rdkit.Chem import rdChemDraw, rdDepictor
from pathlib import Path

rdDepictor.SetPreferCoordGen(True); Path("out").mkdir(exist_ok=True)
for i, smi in enumerate(["CCO", "c1ccccc1", "CC(=O)O"]):
    m = Chem.MolFromSmiles(smi); rdDepictor.Compute2DCoords(m)
    Path(f"out/mol_{i}.cdxml").write_text(rdChemDraw.MolToChemDrawBlock(m), encoding="utf-8")
```

### Recipe: Pretty-print CDXML for inspection

```python
import xml.dom.minidom as minidom
print(minidom.parseString(open("esterification.cdxml", encoding="utf-8").read())
      .toprettyxml(indent="  ")[:1500])
```

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| Exception on `MolToChemDrawBlock` | RDKit built without ChemDraw support | Check `Chem.HasChemDrawCDXSupport()`; install a build with the Revvity parser |
| `UnicodeDecodeError` writing CDX | `rdChemDraw` CDX path is broken | Use legacy `Chem.MolToCDXMLBlock(mol, CDXMLFormat.CDX)`, or write CDXML |
| Structure written flat/overlapping | No 2D coordinates | Call `rdDepictor.Compute2DCoords(mol)` before writing |
| Edited reaction lost arrows/text | File round-tripped through a Mol | Edit the XML tree (`ElementTree`); RDKit writes structures only |
| Reaction won't re-parse | `<step>` references missing ids (collision after merge) | Renumber fragment ids globally unique; update `ReactionStep*` |
| Structures/arrows mismatched size | `<CDXML BondLength="">` empty | Set a numeric `BondLength` (e.g. `30`) on the root |
| `mols` tuple empty on read | Wrong format, or unsanitizable structure | Retry with `sanitize=False`; confirm the file is genuine CDX/CDXML |
| Doubled labels ("OO", "BrBr") | Free-text `<t>` on top of `Element` nodes | Remove the free labels; let `<n Element=...>` render the symbol |
| Stray line crosses a structure | Duplicate or degenerate `<arrow>` | Run `check_scheme`; unique id + real length (`Head3D`≠`Tail3D`) per arrow |
| Conditions text overlaps a structure | Text placed on the structure, not over the arrow gap | Center conditions over the arrow midpoint; widen structure spacing |
| Text renders wrong/blank | non-ASCII, or `<s font>` id missing from `<fonttable>` | Keep text ASCII; reference an existing `font id` |
| No PNG / render error | `epam.indigo` missing, or loaded as molecule when it has arrows | `pip install epam.indigo`; try `loadReaction` before `loadMolecule` |
| "Chiral"/"racemic" printed above structures | Decorative flag text added as `<t>` | Remove it — stereochemistry is shown by wedge bonds; `check_scheme` flags it |
| A name or label sits on an arrow | Text placed on the arrow line | Names go under the structure, conditions offset above/beside the arrow; `check_scheme` flags text on an arrow |
| `stoi: no conversion` loading in Indigo | `<CDXML BondLength="">` empty | Set a numeric `BondLength` (e.g. `30`) before rendering |
| `ModuleNotFoundError`/`FileNotFoundError` on a helper script | `import`ed or `open()`ed the `/SciAgent-Skills/...` path from Python | That path is reachable only via the read-file tool, not the sandbox filesystem — copy the script into the workdir first (Workflow 4), then import |
| `import indigo` fails after a "successful" `pip install` | pip installed into a different Python than the runtime (system `/usr/local` vs the pixi/kernel env) | Install into the running interpreter (`%pip install` or `python -m pip install`), or `pixi add epam.indigo`; don't shell out to a different `python` |
| A charge (`H+`) renders as a giant `+` | Indigo draws a standalone `+` as a reaction-plus symbol, and superscript (face 64) mangles ion text | Keep charges inline (`H+`, `OH-`), face 0 — a true raised superscript is not achievable in the Indigo preview. Subscripts (face 32) and `°C`/`Δ` render fine |

## Bundled Resources

The `scripts/` files can be read from the skill path but **not imported from there** — copy the one you need into your working directory (`read_file` it, write locally), then `import` or run it (see Workflow 4 for the exact copy snippet). Each is self-contained and depends only on rdkit (+ epam.indigo).

- `references/cdxml-schema-reference.md` — element/attribute cheat-sheet (`n`, `b`, `arrow`, `graphic`, `step`/`scheme`, `t`/`s`, `fonttable`, `colortable`), coordinate conventions, enum tables, and a copy-paste document header.
- `scripts/build_reaction_scheme.py` — assemble a multi-step scheme from `(smiles, name, conditions)` steps and render the PNG in one call; auto-sizes cells so structures never overlap. Library (`build_scheme(...)`) or CLI (`python build_reaction_scheme.py steps.json out.cdxml out.png "Title"`).
- `scripts/check_scheme.py` — pre-delivery validator/critic. `check_all(path, expect=..., perspective_ids=...)` rebuilds each molecule from the drawing, sanitizes, prints formulas for a mass-balance check, and flags duplicate ids, fragment overlaps, degenerate arrows, non-ASCII text, decorative flag words ("Chiral"), and labels sitting on an arrow line.

## Related Skills

- **rdkit-cheminformatics** — descriptors, fingerprints, SMARTS; analysis once molecules are parsed
- **datamol-cheminformatics** — higher-level RDKit wrapper for batch standardization before drawing
- **openbabel** — multi-format 2D/3D conversion when you need formats beyond ChemDraw

## References

- [RDKit `rdkit.Chem.rdChemDraw`](https://www.rdkit.org/docs/source/rdkit.Chem.rdChemDraw.html) — `MolsFromChemDraw*`, `ReactionsFromChemDraw*`, `MolToChemDrawBlock`, `CDXFormat`
- [RDKit depiction docs](https://www.rdkit.org/docs/source/rdkit.Chem.Draw.rdMolDraw2D.html) — 2D coordinates and CoordGen
- [CDX/CDXML format specification (CambridgeSoft SDK mirror)](https://chemapps.stolaf.edu/iupac/cdx/sdk/) — arrows, graphics, reactions, text
- [RDKit CDXML test fixtures](https://github.com/rdkit/rdkit/tree/master/Code/GraphMol/test_data/CDXML) — real ChemDraw-authored `.cdxml`
- [Indigo toolkit (`epam.indigo`)](https://lifescience.opensource.epam.com/indigo/) — CDXML loading and PNG rendering
