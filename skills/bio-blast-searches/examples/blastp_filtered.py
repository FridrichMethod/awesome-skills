# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

'''BLASTP with organism filtering'''
from Bio.Blast import NCBIWWW, NCBIXML

# Example protein sequence (hemoglobin alpha)
protein_seq = '''MVLSPADKTNVKAAWGKVGAHAGEYGAEALERMFLSFPTTKTYFPHFDLSH
GSAQVKGHGKKVADALTNAVAHVDDMPNALSALSDLHAHKLRVDPVNFKLLSHCLLVTLAAHLPAEFTPAVHASLDKFLASVSTVLTSKYR'''

protein_seq = protein_seq.replace('\n', '')

print("Running BLASTP against nr (mammals only)...")
print("(This may take 1-2 minutes)\n")

result_handle = NCBIWWW.qblast(
    'blastp',
    'nr',
    protein_seq,
    entrez_query='Mammalia[organism]',
    hitlist_size=15,
    expect=0.001
)

blast_record = NCBIXML.read(result_handle)
result_handle.close()

print(f"Found {len(blast_record.alignments)} hits\n")

print("Top mammalian hits:")
for alignment in blast_record.alignments[:10]:
    hsp = alignment.hsps[0]
    identity_pct = 100 * hsp.identities / hsp.align_length
    print(f"{alignment.accession}: {identity_pct:.1f}% identity, E={hsp.expect:.2e}")
    print(f"  {alignment.title[:60]}...\n")

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
