#  LLM-Driven REAPER Agent (Prototype)

This repository contains a **prototype LLM agent** that can interact with **REAPER** (a digital audio workstation) using natural language.

The agent interprets user instructions, decides when to invoke structured tools, and communicates with REAPER through a lightweight **file-based command / acknowledgment bridge**.

Beyond basic automation, the long-term goal of this project is to explore how an LLM can act as a **creative copilot**—helping users navigate REAPER, understand musical structure, and translate high-level musical intent into concrete DAW actions.

This project is **experimental** and intended as a proof-of-concept rather than a production-ready system.

---

##  Project Status

**Prototype / Research / Demo**

- Built to validate feasibility and architecture
- Not hardened for edge cases or concurrency
- Designed for demos, experimentation, and iteration
- APIs, tools, and internal structure may change significantly

---

##  Features

-  Insert and remove tracks in REAPER
-  Set the project tempo (BPM)
-  Generate a **deterministic basic drum beat**
  - Kick on beat 1
  - Clap on beat 3
  - Hi-hat on every quarter note
-  Browse and search local audio samples
-  Uses an LLM to decide *when* to call tools (not hard-coded command parsing)

---

## 🎼 How This Helps Musicians & Producers

This prototype explores how LLMs can assist **musical workflows**, not just automate them.

### Lowering the Barrier to REAPER
- Users can control REAPER using **plain language** instead of memorizing shortcuts or menus
- Reduces friction for beginners learning DAW concepts like:
  - Tracks
  - Tempo
  - Bars vs beats
  - Sample placement
- Makes REAPER more approachable as a creative environment

### Bridging Musical Intent and Execution
The agent can translate **high-level musical ideas** into deterministic actions:
- “Add a basic beat”
- “Set the tempo to 140 BPM”
- “Put a kick and clap pattern on a new track”

This mirrors how musicians *think* (“I want a groove here”) rather than how DAWs traditionally require interaction.

### Supporting Music Theory Concepts
Although currently minimal, the architecture is designed to support:
- Beat and bar structure
- Meter-aware placement
- Tempo-relative timing
- Explicit reasoning about rhythm and form

This creates a foundation for future extensions involving:
- Chord progressions
- Scale-aware melodic generation
- Harmonic constraints
- Section-based arrangement (verse / chorus / bridge)

### Fast Prototyping & Ideation
- Enables rapid musical sketching without breaking creative flow
- Useful for:
  - Idea generation
  - Rough demos
  - Educational walkthroughs
- Encourages experimentation by reducing setup overhead

---

## Example Prompts

```text
set the tempo to 140 bpm
add a basic beat on track 1
what kick samples do I have?
insert a new track
remove track 2
