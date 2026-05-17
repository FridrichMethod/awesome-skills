# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

'''Download search results as FASTA in batches'''
from Bio import Entrez
import time

Entrez.email = 'your.email@example.com'
# Entrez.api_key = 'your_api_key'  # Uncomment for faster downloads

def download_fasta(term, output_file, batch_size=500):
    # Search with history server
    print(f"Searching: {term}")
    handle = Entrez.esearch(db='nucleotide', term=term, usehistory='y')
    search = Entrez.read(handle)
    handle.close()

    webenv = search['WebEnv']
    query_key = search['QueryKey']
    total = int(search['Count'])

    print(f"Found {total} records")
    if total == 0:
        return

    delay = 0.1 if Entrez.api_key else 0.34

    with open(output_file, 'w') as out:
        for start in range(0, total, batch_size):
            end = min(start + batch_size, total)
            print(f"Downloading {start+1}-{end} of {total}...")

            handle = Entrez.efetch(db='nucleotide', rettype='fasta', retmode='text',
                                   retstart=start, retmax=batch_size,
                                   webenv=webenv, query_key=query_key)
            out.write(handle.read())
            handle.close()

            time.sleep(delay)

    print(f"Saved to {output_file}")

# Example: download human insulin mRNA sequences
download_fasta('human[orgn] AND insulin[gene] AND mRNA[fkey]', 'insulin_mrna.fasta')

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
