---
name: triage
version: 1.0.0
description: "Classify incoming files in brain-inbox for the second brain harvester. Determines processing depth: deep, light, or skip."
author: Second Brain
tags: [second-brain, harvester, triage, classification]
triggers:
  - new file in brain-inbox
  - classify content
  - triage incoming
---

# Triage — Classify Incoming Content

## Purpose

You are the first gate for all content entering the second brain. Your job is to look at an incoming file and decide how much processing it deserves. Fast and cheap — don't over-analyze.

## Classification Levels

### DEEP — Full entity extraction
Content where you were designing, deciding, researching, planning, or learning something substantial. These conversations and documents contain Concepts, Decisions, and relationships worth preserving.

**Signals:** architectural discussion, tool/technology comparison, project planning, business strategy, problem-solving with reasoning, learning a new domain, any "I chose X because Y" patterns.

### LIGHT — Summary + embedding only
Content that's useful to find again but doesn't contain extractable entities or decisions. The value is in the specific solution or information, not generalizable knowledge.

**Signals:** debugging sessions, one-off how-to questions with useful answers, reference lookups, specific code solutions.

### SKIP — No processing
Throwaway interactions with no long-term value.

**Signals:** format conversions, simple translations, "write me a regex", abandoned conversations (no messages or only 1-2 trivial exchanges), small talk, test messages.

## Source-Specific Guidance

### Claude AI JSON (`brain-inbox/claude/`)
- Each file is an array of conversation objects
- Check the `name` field first — it's the conversation title
- Empty `name` + empty `chat_messages` = instant SKIP
- Short `chat_messages` (1-2 exchanges) with generic topics = likely SKIP
- Conversations about your projects, architecture, tools = likely DEEP
- Count messages: <3 messages is almost always SKIP, >10 messages with a specific title is almost always DEEP

### OpenClaw Memory Files (`brain-inbox/openclaw/`)
- Already curated — almost always DEEP
- These are pre-filtered signal, treat them with higher trust

### Grok Export (`brain-inbox/grok/`)
- High noise ratio
- Pure translation requests (English↔Thai) = SKIP
- Translation WITH surrounding context or discussion = LIGHT
- Research, problem-solving, exploration = apply normal rules

### Google Maps / Saved Lists (`brain-inbox/maps/`)
- Always DEEP — these represent real-world decisions and research
- Small files but high signal density

### Unknown Formats (`brain-inbox/other/`)
- Read the file, infer what it is
- Apply the 6-month test: "Would I plausibly want to find this again in 6 months?"
- When uncertain, classify as LIGHT rather than SKIP — better to over-index than lose signal

## Output Format

After classifying, create a front matter block and move the file:

```yaml
---
classification: deep|light|skip
source: claude|openclaw|grok|maps|other
source_file: original_filename.json
timestamp: 2026-04-04T12:00:00Z
reason: "Brief explanation of classification decision"
---
```

- DEEP → move to `brain-inbox/classified/deep/`
- LIGHT → move to `brain-inbox/classified/light/`
- SKIP → move to `brain-inbox/classified/skip/`

## Rules

1. Speed over perfection. You're a router, not an analyzer.
2. When in doubt, go LIGHT. Never SKIP something you're unsure about.
3. Don't read entire conversations for triage. Title + first few messages + message count is usually enough.
4. Log every classification decision for later review.
