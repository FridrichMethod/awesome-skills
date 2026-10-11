# Vector Schematic Style Rules

Conventions for architecture, pipeline, and mechanism schematics drawn with the
[vector schematic workflow](vector-schematic-workflow.md). They bend only when
the figure's own story needs it; say so in the brief when a rule is bent.

## Contents

- [Type](#type)
- [Colour](#colour)
- [Lines and arrows](#lines-and-arrows)
- [Structure](#structure)
- [Legend and numbering](#legend-and-numbering)
- [Common failures](#common-failures)

## Type

- One sans-serif family, at most three sizes, ordinary text 5 to 7 pt at final
  size for the flagship Nature journal; panel letters follow the journal rule.
- Labels are the manuscript's own terms, spelled and capitalised as in the text.
- Text stays live. Do not outline it and do not use a glyph the embedded font
  lacks; draw an ellipsis or arrow as shapes if needed.
- Centre each label in its box, and size the box from the measured label width
  plus padding, not the other way round.

## Colour

- White canvas. At most two saturated fills, and exactly one accent that marks
  the paper's new component.
- Pale or grey fills for existing parts, white with a grey outline for external
  systems.
- Red only for errors, bottlenecks, or a highlighted path.
- Keep text contrast readable: dark text on pale fills, white text only on dark
  accents. Do not rely on colour alone; pair it with a label, shape, or line
  style so the figure survives greyscale printing and colour-vision differences.
- No rainbow categorical fills, gradients, 3D, or drop shadows.

## Lines and arrows

- Every directed edge has an arrowhead; the main path is the heaviest line.
- Solid means data or control that always flows. Dashed carries exactly one
  meaning per figure (for example feedback, or a logical group boundary), never
  two. If groups are dashed, make feedback dotted, or the reverse.
- Use orthogonal routes for structure and curves only for feedback.
- No line passes through a label, and arrows do not end on a container
  boundary unless the whole group is the endpoint.
- Keep arrowheads and tails clear of tier dividers and container titles.

## Structure

- Nest at most three levels. A container is never filled darker than its
  children; outline-only containers are the safe default.
- Equal gaps in a row, and snap box edges to a common grid.
- Place a container title in the headroom between the container's top edge and
  its first box, with no overlap.
- Show repetition with a `×N` mark or a stack of two offset boxes, not N copies.
- Pick one arrangement direction and keep the main path monotone along it.

## Legend and numbering

- Add a legend only when more than four fills, line styles, or icons carry
  meaning and the caption cannot explain them. Place it within one box-width of
  what it decodes.
- Use circled numbers at the upper-left of an edge for the main path, and make
  the numbers match the caption's walkthrough.

## Common failures

| Failure | Fix |
|---|---|
| Too many boxes for the column | Merge, show once with `×N`, or split into two figures |
| Several things in the accent colour | Keep one accent: the new component |
| Dashed used for two meanings | Give one meaning a dotted line or a solid frame |
| Text below the journal floor | Reduce content, never the type |
| Arrow touching a title or crossing a label | Reroute or move the label |
| Decisions made silently | Record them as assumptions in the brief |
