# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

'''Kaplan-Meier survival analysis with log-rank test'''

import pandas as pd
from lifelines import KaplanMeierFitter
from lifelines.statistics import logrank_test
import matplotlib.pyplot as plt

clinical = pd.read_csv('clinical.csv')
print(f'Loaded {len(clinical)} patients')
print(f'Events: {clinical["event"].sum()} ({clinical["event"].mean():.1%})')

fig, ax = plt.subplots(figsize=(8, 6))

groups = clinical['risk_group'].unique()
colors = {'high': 'red', 'low': 'blue'}

for group in groups:
    mask = clinical['risk_group'] == group
    kmf = KaplanMeierFitter()
    kmf.fit(
        clinical.loc[mask, 'survival_time'],
        event_observed=clinical.loc[mask, 'event'],
        label=f'{group} risk (n={mask.sum()})'
    )
    kmf.plot_survival_function(ax=ax, color=colors.get(group, None), ci_show=True)
    median = kmf.median_survival_time_
    # median_survival_time_ is inf if <50% events
    if median != float('inf'):
        print(f'{group} risk median survival: {median:.1f}')

high = clinical[clinical['risk_group'] == 'high']
low = clinical[clinical['risk_group'] == 'low']
lr_results = logrank_test(
    high['survival_time'], low['survival_time'],
    event_observed_A=high['event'], event_observed_B=low['event']
)
print(f'\nLog-rank test: statistic={lr_results.test_statistic:.2f}, p={lr_results.p_value:.4e}')

ax.set_xlabel('Time (months)')
ax.set_ylabel('Survival probability')
ax.set_title(f'Kaplan-Meier survival curves\nLog-rank p = {lr_results.p_value:.4e}')
ax.legend(loc='lower left')
ax.set_ylim(0, 1)

plt.tight_layout()
plt.savefig('kaplan_meier.png', dpi=150)
print('\nSaved kaplan_meier.png')

__AUTHOR_SIGNATURE__ = "9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE"
