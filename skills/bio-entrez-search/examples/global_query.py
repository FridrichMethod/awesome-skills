# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

'''Search across all NCBI databases with Entrez.egquery()'''
from Bio import Entrez

Entrez.email = 'your.email@example.com'

# Global query - search all databases
print('=== Global Query: CRISPR ===')
handle = Entrez.egquery(term='CRISPR')
record = Entrez.read(handle)
handle.close()

print('Databases with matches:')
for result in record['eGQueryResult']:
    count = int(result['Count'])
    if count > 0:
        print(f"  {result['DbName']:20} {count:>10,} records")

# Compare terms across databases
print('\n=== Comparing Terms ===')
terms = ['COVID-19', 'SARS-CoV-2', 'coronavirus']
for term in terms:
    handle = Entrez.egquery(term=term)
    record = Entrez.read(handle)
    handle.close()

    for result in record['eGQueryResult']:
        if result['DbName'] == 'pubmed':
            print(f"PubMed '{term}': {result['Count']} articles")
            break

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
