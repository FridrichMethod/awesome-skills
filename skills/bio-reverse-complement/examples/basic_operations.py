# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

'''Basic reverse complement and complement operations'''
from Bio.Seq import Seq

# Reverse complement (most common)
print('=== Reverse Complement ===')
seq = Seq('ATGCGATCG')
rc = seq.reverse_complement()
print(f'Original:         5\'-{seq}-3\'')
print(f'Reverse comp:     5\'-{rc}-3\'')

# Complement only (less common)
print('\n=== Complement (no reverse) ===')
comp = seq.complement()
print(f'Original:         5\'-{seq}-3\'')
print(f'Complement:       3\'-{comp}-5\'')

# Visualize double-stranded DNA
print('\n=== Double-Stranded Visualization ===')
def show_dsdna(seq):
    comp = seq.complement()
    print(f"5'-{seq}-3'")
    print(f"   {'|' * len(seq)}")
    print(f"3'-{comp}-5'")

show_dsdna(seq)

# RNA reverse complement
print('\n=== RNA Reverse Complement ===')
rna = Seq('AUGCGAUCG')
rc_rna = rna.reverse_complement_rna()
print(f'RNA:          5\'-{rna}-3\'')
print(f'Reverse comp: 5\'-{rc_rna}-3\'')

# Ambiguous bases
print('\n=== Ambiguous Bases ===')
ambig = Seq('ATRYSWKM')
rc_ambig = ambig.reverse_complement()
print(f'Original: {ambig}')
print(f'RevComp:  {rc_ambig}')

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
