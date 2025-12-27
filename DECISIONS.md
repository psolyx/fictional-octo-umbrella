# Architecture Decisions (ADR log)

This document explains how this repository tracks architectural decisions and how to propose new Architecture Decision Records (ADRs).

## Purpose and scope
- ADRs capture consequential technical or product decisions that shape system behavior, constraints, or invariants.
- Use ADRs for choices that are hard to reverse, affect multiple components, or require stakeholder visibility (e.g., security posture, protocol semantics, persistence strategies).
- Routine implementation details, ephemeral experiments, or minor refactors belong in regular documentation (code comments, inline docs, READMEs) rather than ADRs.

## ADR template
Each ADR MUST include the following sections, using the headings exactly:
1. **Status** — Proposed | Accepted | Rejected | Superseded (and link to replacement when superseded).
2. **Context** — Background, forces, and constraints that led to the decision.
3. **Decision** — The selected option and rationale (what was chosen and why).
4. **Consequences** — Positive, negative, and follow-up work implied by the decision.

## Naming and numbering
- Store ADRs under `decisions/` with filenames formatted as `decisions/NNNN-slug.md`.
- `NNNN` is a zero-padded sequence (e.g., `0001`, `0002`).
- The slug is a short, kebab-case summary of the decision.

## Lifecycle and statuses
- **Proposed** — Draft ADR under review; not yet binding.
- **Accepted** — Decision is agreed and expected to be followed.
- **Rejected** — Considered but intentionally not adopted.
- **Superseded** — Replaced by another ADR (link to the successor); historical reference only.

## Process checklist for new ADRs
1. Create a new file using the naming convention (next sequence number + slug) under `decisions/`.
2. Fill in the template sections with concise, reviewable content.
3. Add links to relevant specs or roadmap milestones to ground the context.
4. Mark the initial status as **Proposed**; update to **Accepted** after review/approval.
5. If an ADR replaces an older one, mark the predecessor as **Superseded** and link between them.
6. Reference the ADR from related documentation (e.g., `ARCHITECTURE.md`, `ROADMAP.md`, or component READMEs) when applicable.
