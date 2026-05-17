# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

'''Predict restriction digest fragments'''

from Bio import SeqIO
from Bio.Restriction import EcoRI, BamHI, HindIII

record = SeqIO.read('sequence.fasta', 'fasta')
seq = record.seq

print(f'Sequence: {record.id} ({len(seq)} bp)')
print('=' * 50)

for enzyme in [EcoRI, BamHI, HindIII]:
    sites = enzyme.search(seq)
    if not sites:
        print(f'\n{enzyme}: No cut sites')
        continue

    fragments = enzyme.catalyze(seq)[0]
    sizes = sorted([len(f) for f in fragments], reverse=True)

    print(f'\n{enzyme} ({enzyme.site}):')
    print(f'  Cut sites: {sites}')
    print(f'  Fragments: {len(fragments)}')
    print(f'  Sizes: {sizes}')
    print(f'  Total: {sum(sizes)} bp')

ecori_sites = EcoRI.search(seq)
bamhi_sites = BamHI.search(seq)
all_sites = sorted(set(ecori_sites + bamhi_sites))

if all_sites:
    print(f'\n\nDouble digest (EcoRI + BamHI):')
    print(f'  Combined sites: {all_sites}')

    sizes = []
    sizes.append(all_sites[0])
    for i in range(len(all_sites) - 1):
        sizes.append(all_sites[i + 1] - all_sites[i])
    sizes.append(len(seq) - all_sites[-1])

    sizes = sorted(sizes, reverse=True)
    print(f'  Fragments: {len(sizes)}')
    print(f'  Sizes: {sizes}')

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
