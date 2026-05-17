# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

'''Creating annotated SeqRecords for file output'''
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.SeqFeature import SeqFeature, FeatureLocation

# Basic SeqRecord
record = SeqRecord(
    Seq('ATGCGATCGATCGATCGATCG'),
    id='gene1',
    name='example_gene',
    description='An example gene with annotations'
)

# Add annotations
record.annotations['organism'] = 'Escherichia coli'
record.annotations['molecule_type'] = 'DNA'
record.annotations['topology'] = 'linear'

print('=== SeqRecord with Annotations ===')
print(f'ID: {record.id}')
print(f'Annotations: {record.annotations}')

# Add features
cds_feature = SeqFeature(
    FeatureLocation(0, 21),
    type='CDS',
    qualifiers={'product': ['Example protein'], 'translation': ['MRSIDR']}
)
record.features.append(cds_feature)

print(f'\n=== Features ===')
for feature in record.features:
    print(f'{feature.type}: {feature.location}')
    print(f'  Qualifiers: {feature.qualifiers}')

# Batch create records
print('\n=== Batch Creation ===')
sequences = ['ATGCCC', 'GCTAGC', 'TTAAGG']
records = [SeqRecord(Seq(s), id=f'seq_{i}', description=f'Sequence {i}') for i, s in enumerate(sequences)]
for r in records:
    print(f'{r.id}: {r.seq}')

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
