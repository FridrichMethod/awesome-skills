# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

'''Search GEO for expression datasets'''
from Bio import Entrez

Entrez.email = 'your.email@example.com'

def search_geo_series(term, max_results=20):
    full_term = f'{term} AND gse[entry_type]'
    handle = Entrez.esearch(db='gds', term=full_term, retmax=max_results)
    search = Entrez.read(handle)
    handle.close()

    print(f"Found {search['Count']} total results")

    if not search['IdList']:
        return []

    handle = Entrez.esummary(db='gds', id=','.join(search['IdList']))
    summaries = Entrez.read(handle)
    handle.close()
    return summaries

# Search for breast cancer RNA-seq
print('=== Breast Cancer RNA-Seq ===')
datasets = search_geo_series('breast cancer AND human[orgn] AND expression profiling by high throughput sequencing[gdstype]', max_results=5)
for ds in datasets:
    print(f"{ds['Accession']}: {ds['n_samples']} samples")
    print(f"  {ds['title'][:70]}...")
    print(f"  Platform: {ds['GPL']}")

# Search for specific organism
print('\n=== Mouse Single-Cell ===')
datasets = search_geo_series('single cell AND mouse[orgn] AND RNA-seq', max_results=5)
for ds in datasets:
    print(f"{ds['Accession']}: {ds['n_samples']} samples - {ds['title'][:50]}...")

# Search curated GDS datasets
print('\n=== Curated Datasets (GDS) ===')
handle = Entrez.esearch(db='gds', term='cancer AND human[orgn] AND gds[entry_type]', retmax=5)
search = Entrez.read(handle)
handle.close()

if search['IdList']:
    handle = Entrez.esummary(db='gds', id=','.join(search['IdList']))
    summaries = Entrez.read(handle)
    handle.close()
    for ds in summaries:
        print(f"{ds['Accession']}: {ds['title'][:60]}...")

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
