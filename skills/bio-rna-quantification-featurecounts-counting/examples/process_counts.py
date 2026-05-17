# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

import pandas as pd

counts = pd.read_csv('gene_counts.txt', sep='\t', comment='#')
count_matrix = counts.set_index('Geneid').iloc[:, 5:]
count_matrix.columns = [c.replace('.bam', '').replace('_Aligned.sortedByCoord.out', '')
                        for c in count_matrix.columns]

gene_lengths = counts.set_index('Geneid')['Length']

total_counts = count_matrix.sum()
print('Total counts per sample:')
print(total_counts)

genes_detected = (count_matrix > 0).sum()
print('\nGenes detected per sample:')
print(genes_detected)

count_matrix.to_csv('count_matrix.csv')
gene_lengths.to_csv('gene_lengths.csv')
print('\nSaved count_matrix.csv and gene_lengths.csv')

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
