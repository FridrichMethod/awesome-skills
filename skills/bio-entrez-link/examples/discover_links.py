# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

'''Discover available links from a database record'''
from Bio import Entrez

Entrez.email = 'your.email@example.com'

def discover_all_links(db, record_id):
    handle = Entrez.elink(dbfrom=db, id=record_id, cmd='acheck')
    record = Entrez.read(handle)
    handle.close()

    links = []
    for linkset in record:
        for db_link in linkset.get('LinkSetDb', []):
            links.append({'name': db_link['LinkName'], 'target': db_link['DbTo']})
    return links

# Discover links from a gene
print('=== Available Links from Gene ===')
links = discover_all_links('gene', '672')
for link in links[:15]:
    print(f"  {link['name']:40} -> {link['target']}")

# Discover links from nucleotide
print('\n=== Available Links from Nucleotide ===')
links = discover_all_links('nucleotide', '224589800')
for link in links[:15]:
    print(f"  {link['name']:40} -> {link['target']}")

# Discover links from protein
print('\n=== Available Links from Protein ===')
links = discover_all_links('protein', '119395733')
for link in links[:15]:
    print(f"  {link['name']:40} -> {link['target']}")

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
