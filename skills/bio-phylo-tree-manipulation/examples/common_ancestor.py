# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

'''Find common ancestors and extract subtrees'''

from Bio import Phylo
from io import StringIO

tree_string = '(((Human:0.1,Chimp:0.2):0.1,Gorilla:0.3):0.2,(Mouse:0.4,Rat:0.5):0.6);'
tree = Phylo.read(StringIO(tree_string), 'newick')

print('Full tree:')
Phylo.draw_ascii(tree)

mrca = tree.common_ancestor({'name': 'Human'}, {'name': 'Chimp'})
print(f'\nMRCA of Human and Chimp:')
print(f'Branch length: {mrca.branch_length}')
print(f'Taxa in clade: {[t.name for t in mrca.get_terminals()]}')

primates_mrca = tree.common_ancestor({'name': 'Human'}, {'name': 'Gorilla'})
print(f'\nMRCA of Human and Gorilla (primate clade):')
print(f'Taxa: {[t.name for t in primates_mrca.get_terminals()]}')

taxa = [tree.find_any(name='Human'), tree.find_any(name='Chimp'), tree.find_any(name='Gorilla')]
print(f'\nAre primates monophyletic? {tree.is_monophyletic(taxa)}')

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
