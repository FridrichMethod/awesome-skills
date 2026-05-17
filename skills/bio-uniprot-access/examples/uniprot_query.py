# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

import requests
import pandas as pd
from io import StringIO

def search_uniprot(query, fields, size=500):
    url = 'https://rest.uniprot.org/uniprotkb/search'
    params = {'query': query, 'format': 'tsv', 'fields': ','.join(fields), 'size': size}
    response = requests.get(url, params=params)
    response.raise_for_status()
    return pd.read_csv(StringIO(response.text), sep='\t')

query = 'organism_id:9606 AND keyword:kinase AND reviewed:true'
fields = ['accession', 'gene_names', 'protein_name', 'length', 'go_f']

df = search_uniprot(query, fields)
print(f'Found {len(df)} human kinases in Swiss-Prot')
print(df.head(10))
df.to_csv('human_kinases.csv', index=False)

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
