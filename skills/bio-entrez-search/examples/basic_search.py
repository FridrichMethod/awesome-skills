# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

'''Basic examples of searching NCBI databases with Bio.Entrez'''
from Bio import Entrez

Entrez.email = 'your.email@example.com'

# Simple search
print('=== Simple Nucleotide Search ===')
handle = Entrez.esearch(db='nucleotide', term='human[orgn] AND BRCA1[gene]', retmax=5)
record = Entrez.read(handle)
handle.close()
print(f"Total records: {record['Count']}")
print(f"Returned IDs: {record['IdList']}")

# PubMed search with date range
print('\n=== PubMed Search (2024) ===')
handle = Entrez.esearch(db='pubmed', term='CRISPR', mindate='2024/01/01', maxdate='2024/12/31', datetype='pdat', retmax=5)
record = Entrez.read(handle)
handle.close()
print(f"CRISPR papers in 2024: {record['Count']}")

# Search with boolean operators
print('\n=== Boolean Search ===')
handle = Entrez.esearch(db='nucleotide', term='(mouse[orgn] OR rat[orgn]) AND insulin[gene]', retmax=5)
record = Entrez.read(handle)
handle.close()
print(f"Mouse/rat insulin records: {record['Count']}")

# Check query translation
print('\n=== Query Translation ===')
handle = Entrez.esearch(db='nucleotide', term='e coli lac operon')
record = Entrez.read(handle)
handle.close()
print(f"Original: e coli lac operon")
print(f"Translated: {record['QueryTranslation']}")

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
