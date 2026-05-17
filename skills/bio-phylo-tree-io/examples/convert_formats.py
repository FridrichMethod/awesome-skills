# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

'''Convert phylogenetic tree between formats'''

from Bio import Phylo
from io import StringIO

tree_string = '((A:0.1,B:0.2):0.3,(C:0.4,D:0.5):0.6);'
tree = Phylo.read(StringIO(tree_string), 'newick')

Phylo.write(tree, 'output.xml', 'phyloxml')
print('Converted Newick to PhyloXML')

Phylo.convert('output.xml', 'phyloxml', 'output.nex', 'nexus')
print('Converted PhyloXML to Nexus')

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
