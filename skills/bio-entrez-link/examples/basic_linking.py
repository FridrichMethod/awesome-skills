# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

'''Basic cross-database linking with Entrez.elink()'''
from Bio import Entrez

Entrez.email = 'your.email@example.com'

# Gene to protein
print('=== Gene to Protein ===')
handle = Entrez.elink(dbfrom='gene', db='protein', id='672', linkname='gene_protein_refseq')
record = Entrez.read(handle)
handle.close()

if record[0]['LinkSetDb']:
    links = record[0]['LinkSetDb'][0]['Link']
    protein_ids = [link['Id'] for link in links[:5]]
    print(f"Gene 672 (BRCA1) RefSeq proteins: {protein_ids}")
else:
    print("No protein links found")

# Nucleotide to gene
print('\n=== Nucleotide to Gene ===')
handle = Entrez.elink(dbfrom='nucleotide', db='gene', id='224589800')
record = Entrez.read(handle)
handle.close()

if record[0]['LinkSetDb']:
    gene_id = record[0]['LinkSetDb'][0]['Link'][0]['Id']
    print(f"Nucleotide maps to gene: {gene_id}")

# Related PubMed articles
print('\n=== Related PubMed Articles ===')
handle = Entrez.elink(dbfrom='pubmed', db='pubmed', id='35412348', linkname='pubmed_pubmed')
record = Entrez.read(handle)
handle.close()

if record[0]['LinkSetDb']:
    related = [link['Id'] for link in record[0]['LinkSetDb'][0]['Link'][:5]]
    print(f"Related articles: {related}")

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
