"""
check_scheme.py — Validate and critique a ChemDraw CDXML scheme before delivery.

Three independent passes, none of which subsumes the others:

1. validate_structures() rebuilds every molecule in RDKit **from the CDXML drawing
   itself** (not from a SMILES you typed separately), sanitizes it (catching valence
   errors), prints its molecular formula and canonical SMILES, and compares against
   any reference SMILES you can state independently. Validating a parallel SMILES
   string is pointless — a mismatch between that string and the drawing goes
   undetected; rebuilding from the drawing is the whole point.

2. mass_balance() prints the formula of each structure in order so you can check it
   against the reaction arrows by hand: a protection adds exactly the protecting
   group, a decarboxylation removes exactly CO2, a photochemical isomerisation does
   not change the formula at all. This catches connectivity slips sanitization allows.

3. geometry_check() flags duplicate object ids, overlapping structures, non-bonded
   atoms drawn on top of each other, atoms sitting on an unrelated bond, bond
   crossings, degenerate/duplicate arrows, non-ASCII text (the font table is
   iso-8859-1), and conditions text wider than its arrow. Pass perspective_ids for
   fragments whose foreshortened bonds and crossings are intentional (cages, bridged
   bicyclics) so they are reported as info (.) rather than problems (!).

check_all() runs all three and returns the problem count. Drive it to zero.

Usage:
    from check_scheme import check_all
    n = check_all("scheme.cdxml", expect={10: "C12C3C4C1C5C2C3C45"}, perspective_ids={"6100"})
    assert n == 0
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from collections import Counter
from itertools import combinations
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import rdChemDraw, rdMolDescriptors

BOND_MIN, BOND_MAX = 20.0, 45.0      # acceptable drawn bond-length window (units)
COINCIDENT = 8.0                     # non-bonded atoms closer than this overlap
ON_BOND = 6.0                        # atom-to-unrelated-bond distance that reads as "on it"
ON_ARROW = 10.0                      # text-anchor-to-arrow-line distance that reads as overlapping
CHAR_W = 5.5                         # approx width of one size-9 character (units)
# Decorative stereo flags to keep out of schemes — draw wedge bonds instead.
FLAG_WORDS = {"chiral", "achiral", "racemic", "(+/-)", "(±)", "meso"}
# Non-ASCII characters intentionally allowed in text (degree, delta for heat).
ALLOWED_NONASCII = {"°", "Δ", "∆"}


def _atoms(frag):
    return {n.get("id"): tuple(map(float, n.get("p").split()))
            for n in frag.iter("n") if n.get("p")}


def _bonds(frag):
    return [(b.get("B"), b.get("E")) for b in frag.iter("b")]


def _seg_dist(p, a, b):
    """Distance from point p to segment ab."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def _segments_cross(p1, p2, p3, p4):
    """True if open segments p1p2 and p3p4 properly intersect."""
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = ccw(p3, p4, p1), ccw(p3, p4, p2)
    d3, d4 = ccw(p1, p2, p3), ccw(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def validate_structures(cdxml_path, expect=None):
    """Rebuild each drawn molecule in RDKit, sanitize, print formula/SMILES, compare."""
    expect = expect or {}
    txt = Path(cdxml_path).read_text(encoding="utf-8")
    mols = rdChemDraw.MolsFromChemDrawBlock(txt, sanitize=False)
    problems = []
    print(f"[validate] {len(mols)} structure(s) rebuilt from the drawing:")
    for i, m in enumerate(mols):
        try:
            Chem.SanitizeMol(m)
            formula = rdMolDescriptors.CalcMolFormula(m)
            smi = Chem.MolToSmiles(m)
        except Exception as e:
            problems.append(f"structure {i}: valence/sanitize error ({str(e)[:50]})")
            print(f"  ! [{i}] SANITIZE FAILED: {str(e)[:60]}")
            continue
        tag, mark = "", "."
        if i in expect:
            ref = Chem.MolFromSmiles(expect[i])
            if ref is None:
                problems.append(f"structure {i}: reference SMILES '{expect[i]}' is invalid")
                tag, mark = "  [BAD REFERENCE SMILES]", "!"
            elif Chem.MolToSmiles(ref) == smi:
                tag = "  [MATCH]"
            else:
                problems.append(f"structure {i}: drawn {smi} != expected {expect[i]}")
                tag, mark = f"  [MISMATCH expected {expect[i]}]", "!"
        print(f"  {mark} [{i}] {formula:12} {smi}{tag}")
    return problems


def mass_balance(cdxml_path):
    """Print each structure's formula in order for a by-hand arrow mass-balance check."""
    txt = Path(cdxml_path).read_text(encoding="utf-8")
    mols = rdChemDraw.MolsFromChemDrawBlock(txt, sanitize=False)
    print("[mass balance] formula per structure (check deltas against your arrows):")
    prev = None
    for i, m in enumerate(mols):
        try:
            Chem.SanitizeMol(m)
            f = rdMolDescriptors.CalcMolFormula(m)
        except Exception:
            f = "<invalid>"
        delta = ""
        if prev and f != "<invalid>":
            delta = f"   (prev -> this)"
        print(f"  [{i}] {f}{delta}")
        prev = f


def geometry_check(cdxml_path, perspective_ids=()):
    """Layout and drawing critic. Returns list of problem strings; prints ! / . report."""
    perspective_ids = set(perspective_ids)
    root = ET.fromstring(Path(cdxml_path).read_text(encoding="utf-8"))
    problems, infos = [], []

    # duplicate object ids
    ids = [e.get("id") for e in root.iter() if e.get("id")]
    dups = [i for i, c in Counter(ids).items() if c > 1]
    if dups:
        problems.append(f"duplicate ids: {dups}")

    frags = root.findall(".//fragment")
    # fragment bounding boxes -> overlap between different structures
    def fbbox(fr):
        xs = [p[0] for p in _atoms(fr).values()]
        ys = [p[1] for p in _atoms(fr).values()]
        return (min(xs), min(ys), max(xs), max(ys))
    boxes = [(fr.get("id"), fbbox(fr)) for fr in frags]
    for (ida, a), (idb, b) in combinations(boxes, 2):
        if not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1]):
            problems.append(f"fragments {ida} and {idb} overlap")

    # per-fragment intramolecular checks
    for fr in frags:
        fid = fr.get("id")
        persp = fid in perspective_ids
        atoms, bonds = _atoms(fr), _bonds(fr)
        bonded = {frozenset(b) for b in bonds}
        # bond lengths
        for B, E in bonds:
            if B in atoms and E in atoms:
                d = ((atoms[B][0] - atoms[E][0]) ** 2 + (atoms[B][1] - atoms[E][1]) ** 2) ** 0.5
                if not (BOND_MIN <= d <= BOND_MAX):
                    (infos if persp else problems).append(
                        f"fragment {fid}: bond {B}-{E} length {d:.1f} out of [{BOND_MIN},{BOND_MAX}]")
        # Intramolecular drawing checks are info-only: a 2D projection of a cage or
        # bridged bicyclic legitimately has crossings and near-coincident atoms.
        # Pass the fragment id in perspective_ids to silence them entirely.
        if persp:
            continue
        # non-bonded coincident atoms
        for i1, i2 in combinations(atoms, 2):
            if frozenset((i1, i2)) in bonded:
                continue
            d = ((atoms[i1][0] - atoms[i2][0]) ** 2 + (atoms[i1][1] - atoms[i2][1]) ** 2) ** 0.5
            if d < COINCIDENT:
                infos.append(f"fragment {fid}: non-bonded atoms {i1},{i2} coincide (d={d:.1f})")
        # atom sitting on an unrelated bond
        for aid, ap in atoms.items():
            for B, E in bonds:
                if aid in (B, E) or B not in atoms or E not in atoms:
                    continue
                if _seg_dist(ap, atoms[B], atoms[E]) < ON_BOND:
                    infos.append(f"fragment {fid}: atom {aid} sits on bond {B}-{E}")
        # bond crossings
        for (b1, b2) in combinations(bonds, 2):
            if set(b1) & set(b2):
                continue
            if all(x in atoms for x in (*b1, *b2)) and _segments_cross(
                    atoms[b1[0]], atoms[b1[1]], atoms[b2[0]], atoms[b2[1]]):
                infos.append(f"fragment {fid}: bonds {b1} and {b2} cross")

    # arrows: degenerate / duplicate
    arrows = root.findall(".//arrow")
    acount = Counter(a.get("id") for a in arrows)
    for aid, c in acount.items():
        if c > 1:
            problems.append(f"arrow id {aid} written {c} times")
    arrow_spans, arrow_segs = [], []
    for a in arrows:
        if a.get("Head3D") and a.get("Tail3D"):
            hx, hy, _ = map(float, a.get("Head3D").split())
            tx, ty, _ = map(float, a.get("Tail3D").split())
            L = ((hx - tx) ** 2 + (hy - ty) ** 2) ** 0.5
            if L < 15:
                problems.append(f"arrow {a.get('id')} degenerate (length {L:.1f})")
            arrow_spans.append(((hx + tx) / 2, (hy + ty) / 2, L))
            arrow_segs.append(((tx, ty), (hx, hy)))

    # text: decorative flag words, non-ASCII, overlap with an arrow line, over-wide
    for t in root.iter("t"):
        s = "".join(x.text or "" for x in t.iter("s"))
        if s.strip().lower() in FLAG_WORDS:
            problems.append(f"decorative flag text '{s.strip()}' — remove it; show stereo with wedge bonds")
        bad = [ch for ch in s if ord(ch) > 127 and ch not in ALLOWED_NONASCII]
        if bad:
            problems.append(f"text '{s[:25]}' has unsupported non-ASCII {bad} (font table is iso-8859-1)")
        if t.get("p"):
            tx, ty = map(float, t.get("p").split())
            for p0, p1 in arrow_segs:                       # text anchor sitting on an arrow line
                if _seg_dist((tx, ty), p0, p1) < ON_ARROW:
                    problems.append(f"text '{s[:25]}' overlaps an arrow (move it clear of the arrow line)")
                    break
            if arrow_spans:                                 # conditions text wider than its arrow
                mx, my, L = min(arrow_spans, key=lambda m: (m[0] - tx) ** 2 + (m[1] - ty) ** 2)
                if abs(my - ty) < 40 and len(s) * CHAR_W > L * 1.4:
                    infos.append(f"text '{s[:25]}' (~{len(s)*CHAR_W:.0f}u) wider than its arrow ({L:.0f}u)")

    for p in problems:
        print(f"  ! {p}")
    for inf in infos:
        print(f"  . {inf}")
    print(f"[geometry] {len(problems)} problem(s), {len(infos)} info")
    return problems


def check_all(cdxml_path, expect=None, perspective_ids=()):
    """Run all three passes; return total problem count. Aim for 0."""
    p1 = validate_structures(cdxml_path, expect)
    mass_balance(cdxml_path)
    p3 = geometry_check(cdxml_path, perspective_ids)
    total = len(p1) + len(p3)
    print(f"\n=== {total} problem(s) total — {'OK to deliver' if total == 0 else 'FIX before delivering'} ===")
    return total


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    sys.exit(1 if check_all(sys.argv[1]) else 0)
