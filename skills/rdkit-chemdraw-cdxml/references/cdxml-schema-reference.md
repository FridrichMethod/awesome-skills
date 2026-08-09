# CDXML Schema Reference (ChemDraw)

Distilled from the CambridgeSoft/Revvity CDX/CDXML SDK specification
(<https://chemapps.stolaf.edu/iupac/cdx/sdk/>) and cross-checked against real
ChemDraw-authored files in the RDKit test corpus. CDXML is plain XML with **no
namespace** and **case-sensitive** element names, so `xml.etree.ElementTree`
handles it directly.

## Document skeleton

```xml
<?xml version="1.0" encoding="UTF-8"?>
<CDXML BondLength="30">
  <colortable>
    <color r="1" g="1" b="1"/>   <!-- index 0 -->
    <color r="0" g="0" b="0"/>   <!-- index 1 (indices count from the SECOND color in some readers) -->
  </colortable>
  <fonttable>
    <font id="21" charset="x-mac-roman" name="Helvetica"/>
  </fonttable>
  <page>
    <fragment>…</fragment>       <!-- molecules -->
    <graphic/> <arrow/> <t>…</t> <!-- plus signs, arrows, text -->
    <scheme><step .../></scheme> <!-- reaction wiring -->
  </page>
</CDXML>
```

- `id` is a unique integer on (almost) every object; other objects reference it.
- Coordinates: **y increases downward**, origin top-left. Default `BondLength` ≈ 30.
- Positions: `p="x y"`. Bounding boxes: `BoundingBox="x1 y1 x2 y2"`.

## Recommended document header (copy-paste)

RDKit writes a minimal `<CDXML BondLength="">` root. Files that render cleanly and
consistently in ChemDraw carry a fuller header, standard color table, and page
dimensions. Use this template when assembling a document by hand:

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<!DOCTYPE CDXML SYSTEM "http://www.cambridgesoft.com/xml/cdxml.dtd" >
<CDXML CreationProgram="my-generator" BondLength="30"
       LabelFont="3" LabelSize="10" CaptionFont="3" CaptionSize="10"
       HashSpacing="2.50" MarginWidth="1.60" LineWidth="0.60" BoldWidth="2"
       BondSpacing="12" ChainAngle="120" color="0" bgcolor="1">
  <colortable>                 <!-- standard 8-color ChemDraw table -->
    <color r="1" g="1" b="1"/> <!-- 0 white / background -->
    <color r="0" g="0" b="0"/> <!-- 1 black -->
    <color r="1" g="0" b="0"/> <!-- 2 red -->
    <color r="1" g="1" b="0"/> <!-- 3 yellow -->
    <color r="0" g="1" b="0"/> <!-- 4 green -->
    <color r="0" g="1" b="1"/> <!-- 5 cyan -->
    <color r="0" g="0" b="1"/> <!-- 6 blue -->
    <color r="1" g="0" b="1"/> <!-- 7 magenta -->
  </colortable>
  <fonttable>
    <font id="3" charset="iso-8859-1" name="Arial"/>
    <font id="4" charset="iso-8859-1" name="Times New Roman"/>
  </fonttable>
  <page id="99" HeightPages="1" WidthPages="1" Width="940" Height="940"
        BoundingBox="0 0 940 940" DrawingSpace="poster">
    <!-- fragments, arrows, text, scheme go here -->
  </page>
</CDXML>
```

Size the `<page>` `Width`/`Height`/`BoundingBox` to the actual extent of the
drawing (a multi-step scheme needs a large "poster" space); a page smaller than
the content clips it in ChemDraw.

## Molecule objects

| Element | Meaning | Key attributes |
|---------|---------|----------------|
| `fragment` | one connected molecule | `id` |
| `n` | node (atom) | `id`, `p="x y"`, `Element` (atomic number; omitted → carbon), `Charge`, `NumHydrogens`, `NodeType` |
| `b` | bond | `id`, `B` (begin node id), `E` (end node id), `Order` (omitted → 1; `2`, `3`, `1.5`), `Display` (`WedgeBegin`, `WedgeEnd`, `Hash`, …) |

```xml
<fragment id="3">
  <n id="4" p="-76.7 -9.0"/>              <!-- carbon -->
  <n id="6" p="-51.9 34.2" Element="8"/>  <!-- oxygen -->
  <b id="18" B="5" E="6" Order="2"/>      <!-- C=O -->
</fragment>
```

## Arrow objects

Two representations exist; ChemDraw writes both (the `<graphic>` line is often
`SupersededBy` the modern `<arrow>`). A reaction `<step>` may reference **either** id.

### Modern `<arrow>`

```xml
<arrow id="396" BoundingBox="329.6 236.3 389.8 248.5"
       FillType="None" ArrowheadHead="Full" ArrowheadType="Solid"
       HeadSize="2250" ArrowheadCenterSize="1969" ArrowheadWidth="563"
       Head3D="389.8 242.9 0" Tail3D="329.6 242.9 0"/>
```

| Attribute | Meaning |
|-----------|---------|
| `Tail3D`, `Head3D` | start/end points `"x y z"` (z usually 0) |
| `ArrowheadHead` | `Full`, `HalfLeft`, `HalfRight`, `None` |
| `ArrowheadType` | `Solid`, `Hollow`, `Angle` |
| `HeadSize`, `ArrowheadWidth` | arrowhead geometry (CDXML units ×100) |
| `FillType` | `None`, `Solid` |

### Legacy `<graphic>` line-arrow

```xml
<graphic id="327" GraphicType="Line" ArrowType="FullHead"
         HeadSize="2250" BoundingBox="389.8 242.9 329.6 242.9"/>
```

`ArrowType` enumeration (bit-combinable): `NoHead`(0), `HalfHead`(1),
`FullHead`(2), `Resonance`(4), `Equilibrium`(8), `Hollow`(16),
`RetroSynthetic`(32), `NoGo`(64, crossed-out/failed), `Dipole`(128).

## Graphic objects (non-arrow)

`GraphicType` enumeration: `Undefined`(0), `Line`(1), `Arc`(2), `Rectangle`(3),
`Oval`(4), `Orbital`(5), `Bracket`(6), `Symbol`(7).

For graphics, `BoundingBox` is a **pair of points**, not a rectangle — its
meaning depends on the type (e.g. Line = start+end; Arc = center+end).

### Reaction plus sign (`Symbol`)

```xml
<graphic id="318" GraphicType="Symbol" SymbolType="Plus"
         BoundingBox="178.4 242.9 178.4 250.4"/>
```

`SymbolType` values include `Plus`, `Minus`, `LonePair`, `Dagger`, `Charge*`.

## Reaction wiring: `<scheme>` and `<step>`

A `<scheme>` (CDXML name `scheme`) contains one or more `<step>` objects. The
step holds no geometry — it references page objects by id.

```xml
<scheme id="397">
  <step id="398"
        ReactionStepReactants="303 320"
        ReactionStepProducts="369"
        ReactionStepArrows="327"
        ReactionStepPlusses="318"
        ReactionStepObjectsAboveArrow="410"
        ReactionStepObjectsBelowArrow="411"
        ReactionStepAtomMap="306 348 300 354"/>   <!-- reactant→product atom id pairs -->
</scheme>
```

| Attribute | Contents (space-separated object-id list) |
|-----------|-------------------------------------------|
| `ReactionStepReactants` | reactant fragment ids, in order |
| `ReactionStepProducts` | product fragment ids |
| `ReactionStepArrows` | arrow/graphic-line ids |
| `ReactionStepPlusses` | plus-symbol graphic ids |
| `ReactionStepObjectsAboveArrow` / `…BelowArrow` | ids of text/fragments as conditions |
| `ReactionStepAtomMap` | flat list of mapped atom-id pairs |

## Text objects: `<t>` and `<s>`

A `<t>` block is positioned by `p`; it holds one or more `<s>` (style) runs, each
a single style. `<s>` references a `font` id and `color` index; `size` is in
points; `face` is a style bitmask.

```xml
<t p="137.4 218.1" BoundingBox="137.8 210.8 146.1 218.3"
   LabelJustification="Left" Justification="Left">
  <s font="21" size="10" color="0" face="96">Cl</s>
</t>
```

| `<t>` attribute | Meaning |
|-----------------|---------|
| `p` | anchor position `"x y"` |
| `BoundingBox` | enclosing rectangle |
| `Justification` | text alignment (`Left`, `Center`, `Right`) |
| `LabelJustification` | alignment when used as an atom label |

`<s>` **face** bitmask: `1`=Bold, `2`=Italic, `4`=Underline, `8`=Outline,
`16`=Shadow, `32`=Subscript, `64`=Superscript (ChemDraw combines these; the
value `96` = subscript+superscript flags seen on formula labels). `color`
indexes the `<colortable>`; `font` matches a `<font id>` in `<fonttable>`.

## fonttable / colortable

```xml
<fonttable>
  <font id="21" charset="x-mac-roman" name="Helvetica"/>
</fonttable>
<colortable>
  <color r="1" g="1" b="1"/>   <!-- r,g,b in 0..1 -->
  <color r="0" g="0" b="0"/>
</colortable>
```

Any `<s font="…">` and `<s color="…">` must reference ids/indices that exist in
these tables, or ChemDraw falls back to defaults. When editing an existing file,
reuse its tables rather than adding duplicates.

## Practical assembly rules

1. **Globally unique ids.** Merging fragments from separate RDKit outputs (each
   starting ids at 1) collides — renumber into disjoint blocks first, and fix
   every `b B/E` and `ReactionStep*` reference to match.
2. **Set `BondLength`.** RDKit writes `BondLength=""`; put a number (≈30) so
   arrows/text scale consistently with structures.
3. **Position with real coordinates.** Fragments carry their own atom coordinates
   from RDKit; shift them (add `dx`/`dy` to each `n p`) rather than relying on
   ChemDraw auto-layout.
4. **Validate by re-reading.** `rdChemReactions.ReactionsFromCDXMLBlock(text)`
   should return the expected reactant/product counts if the `<step>` id
   references are correct.
