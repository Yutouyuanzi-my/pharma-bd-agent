# Product Requirements Document: Pharma BD Competitive Intelligence Agent

## 1. Problem Statement

**Problem**: Pharma Business Development professionals spend 2-3 hours every
morning manually checking ClinicalTrials.gov for competitor updates: new
registrations, status changes, phase transitions. Current workflow is manual,
error-prone, and doesn't scale across multiple therapeutic areas.

**Target users**:
- Primary: Pharma BD / Corporate Strategy analysts
- Secondary: Competitive Intelligence teams at biotech and pharma companies
- Tertiary: VC investors tracking therapeutic area activity

## 2. User Stories

| Priority | Story |
|---|---|
| P0 | As a BD analyst, I want to see all new trials in my therapeutic area from the past week |
| P0 | As a BD analyst, I want to know what each competitor is doing in a specific indication |
| P1 | As a BD analyst, I want a landscape overview: which sponsors, phases, and how many trials |
| P1 | As a BD analyst, I want to compare competitor trials side-by-side |
| P2 | As a BD analyst, I want to receive daily email/Slack briefings automatically |
| P3 | As a BD director, I want to track multiple therapeutic areas simultaneously |

## 3. Functional Requirements

### Agent MVP
- F1: Search trials by condition, sponsor/company, and status
- F2: Competitive landscape analysis (sponsor grouping, phase distribution, LLM summary)
- F3: Recent change monitoring (daily/weekly new & updated trials)
- F4: Side-by-side trial comparison
- F5: Multi-language output (Chinese primary, English secondary)

### V1 Enhancements
- F6: Automated daily briefing via email / Slack webhook
- F7: Saved watchlists (condition + sponsor combinations)
- F8: Add EU Clinical Trials Register and ChiCTR data sources

## 4. Success Metrics

| Metric | Target |
|---|---|
| Time savings per analyst/day | 2+ hours |
| Missed trial detection rate | < 5% |
| Alert latency (trial posted → user notified) | < 24 hours |
| User retention (weekly active) | > 80% |

## 5. Technical Architecture

```
[Streamlit UI] → [Agent Controller (OpenAI FC)] → [Tool Layer]
                                                    ├─ ClinicalTrials.gov API (v2)
                                                    ├─ PubMed E-utilities API
                                                    └─ LLM Analysis (gpt-4o-mini)
```

Key design decisions: pure OpenAI function calling (no agent framework),
Chinese-first output, async-ready tool layer.

## 6. Competitive Landscape

| Product | Strengths | Weaknesses |
|---|---|---|
| Cortellis (Clarivate) | Comprehensive, includes deals data | Expensive ($10k+/yr), closed data |
| GlobalData | Good for pharma | No real-time trial monitoring |
| ClinicalTrials.gov native | Free, authoritative | No personalization, no monitoring |
| **Ours** | Free + AI-powered, BD-focused, Chinese support | MVP stage, US data only |

## 7. Risk & Mitigation

| Risk | Mitigation |
|---|---|
| ClinicalTrials.gov API throttling | Caching, staggered queries |
| WAF blocks cloud IPs | Local relay / residential proxy |
| LLM hallucination on competitive analysis | Structured data first, LLM as summarizer only |
| Data source limited to US | Roadmap includes EU + China registries |

## 8. Next Steps

1. ✅ MVP: Agent with 6 tools for BD intelligence
2. ⬜ User testing with 3 pharma BD professionals
3. ⬜ Automated daily briefing delivery (cron + email)
4. ⬜ Multi-source: EUCTR + ChiCTR integration
5. ⬜ Dify workflow parallel build (for PM validation)
