# `nature-experiment-log` Skill

[中文说明](README.md)

`nature-experiment-log` turns experiment images, voice notes, text, and scattered observations into traceable structured experiment logs for Obsidian or plain Markdown workflows.

## What To Use It For

- Turn a day's experiment record into a standard log with YAML frontmatter.
- Extract experiment elements from photos, microscopy images, weighing notes, instrument screenshots, or voice transcripts.
- Link samples, conditions, observations, anomalies, next actions, and raw attachments.
- Archive raw materials from Feishu, chat records, or CLI input into the same experiment-log format.

## Typical Requests

- "Record an experiment: 316L chloride-salt corrosion at 500°C for 300 h in Ar, mass loss 0.0032 g."
- "Turn these experiment photos into today's Obsidian lab log."
- "Use this voice transcript to create a standard experiment record and list missing information."

## What You Need To Provide

- Experiment date, sample, conditions, steps, observations, or raw attachments.
- Target vault / output directory; if not specified, the skill generates Markdown that can be saved.
- Required naming rules, project IDs, or sample IDs.

## Outputs

- Experiment log with YAML frontmatter.
- Attachment index for source images, audio, tables, or chat records.
- Missing-field checklist and suggested next experiment actions.

## Boundaries

- The skill does not invent temperature, duration, recipe, device model, or results.
- Unconfirmed information is preserved as `AUTHOR_INPUT_NEEDED` or Chinese confirmation items.
- Feishu, Obsidian, or other external write paths depend on local CLI configuration or directory permissions.

## Related Skills

- `nature-data`: turn experiment data into Data Availability and FAIR checklists.
- `nature-figure`: turn experiment data or images into submission-grade figures.
