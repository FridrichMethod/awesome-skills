# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

'''Root a tree using an outgroup or midpoint'''

from Bio import Phylo
from io import StringIO

tree_string = '((Human:0.1,Chimp:0.2):0.3,(Mouse:0.4,Rat:0.5):0.6,Zebrafish:1.0);'
tree = Phylo.read(StringIO(tree_string), 'newick')

print('Original tree:')
Phylo.draw_ascii(tree)

tree.root_with_outgroup({'name': 'Zebrafish'})
print('\nRooted with Zebrafish as outgroup:')
Phylo.draw_ascii(tree)

tree2 = Phylo.read(StringIO(tree_string), 'newick')
tree2.root_at_midpoint()
print('\nRooted at midpoint:')
Phylo.draw_ascii(tree2)

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
