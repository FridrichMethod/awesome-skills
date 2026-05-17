# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

'''Parse multiple trees from a single file'''

from Bio import Phylo
from io import StringIO

multi_tree_string = '''((A,B),(C,D));
((A,C),(B,D));
((A,D),(B,C));'''

trees = list(Phylo.parse(StringIO(multi_tree_string), 'newick'))
print(f'Loaded {len(trees)} trees\n')

for i, tree in enumerate(trees):
    terminals = [t.name for t in tree.get_terminals()]
    print(f'Tree {i+1}: {terminals}')

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
