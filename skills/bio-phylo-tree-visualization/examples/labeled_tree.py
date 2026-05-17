# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

'''Draw tree with custom labels and branch lengths'''

from Bio import Phylo
from io import StringIO
import matplotlib.pyplot as plt

tree_string = '((A:0.15,B:0.22):0.08,(C:0.35,D:0.41):0.12);'
tree = Phylo.read(StringIO(tree_string), 'newick')
tree.ladderize()

def branch_labels(clade):
    if clade.branch_length:
        return f'{clade.branch_length:.2f}'
    return ''

fig, ax = plt.subplots(figsize=(10, 6))
Phylo.draw(tree, axes=ax, do_show=False, branch_labels=branch_labels)
ax.set_title('Tree with Branch Lengths')
plt.savefig('labeled_tree.png', dpi=300, bbox_inches='tight')
plt.close()
print('Saved to labeled_tree.png')

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
