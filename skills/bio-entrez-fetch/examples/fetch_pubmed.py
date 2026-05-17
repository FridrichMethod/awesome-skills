# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

'''Fetch PubMed records in various formats'''
from Bio import Entrez

Entrez.email = 'your.email@example.com'

pmid = '35412348'

# Fetch abstract
print('=== Abstract ===')
handle = Entrez.efetch(db='pubmed', id=pmid, rettype='abstract', retmode='text')
abstract = handle.read()
handle.close()
print(abstract[:500] + '...')

# Fetch MEDLINE format
print('\n=== MEDLINE Format ===')
handle = Entrez.efetch(db='pubmed', id=pmid, rettype='medline', retmode='text')
medline = handle.read()
handle.close()
print(medline[:400] + '...')

# Fetch XML for structured parsing
print('\n=== XML Parsing ===')
handle = Entrez.efetch(db='pubmed', id=pmid, retmode='xml')
records = Entrez.read(handle)
handle.close()

article = records['PubmedArticle'][0]['MedlineCitation']['Article']
print(f"Title: {article['ArticleTitle']}")
print(f"Journal: {article['Journal']['Title']}")

authors = article.get('AuthorList', [])
if authors:
    first_author = authors[0]
    name = f"{first_author.get('LastName', '')} {first_author.get('Initials', '')}"
    print(f"First author: {name}")

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
