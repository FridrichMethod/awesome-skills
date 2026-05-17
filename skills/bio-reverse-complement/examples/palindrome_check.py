# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

'''Check for palindromic sequences (restriction sites)'''
from Bio.Seq import Seq

def is_palindrome(seq):
    '''Check if sequence equals its reverse complement'''
    return seq == seq.reverse_complement()

# Common restriction enzyme sites
sites = {
    'EcoRI': 'GAATTC',
    'BamHI': 'GGATCC',
    'HindIII': 'AAGCTT',
    'NotI': 'GCGGCCGC',
    'XhoI': 'CTCGAG',
    'Random': 'ATGCGA'
}

print('=== Palindrome Check ===')
for name, site in sites.items():
    seq = Seq(site)
    rc = seq.reverse_complement()
    is_pal = is_palindrome(seq)
    print(f'{name:10} {site:10} RC: {rc}  Palindrome: {is_pal}')

# Find palindromes of a given length in a sequence
print('\n=== Find Palindromes in Sequence ===')
def find_palindromes(seq, length=6):
    '''Find all palindromic subsequences of given length'''
    palindromes = []
    for i in range(len(seq) - length + 1):
        subseq = seq[i:i + length]
        if is_palindrome(subseq):
            palindromes.append((i, str(subseq)))
    return palindromes

test_seq = Seq('ATGCGAATTCGATGGATCCATG')
for pos, pal in find_palindromes(test_seq, 6):
    print(f'Position {pos}: {pal}')

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
