# LLM-Driven REAPER Agent (Prototype)

This repository contains a **prototype LLM agent** that can interact with **REAPER** (a digital audio workstation) using natural language.

The agent interprets user instructions, decides when to invoke structured tools, and communicates with REAPER through a lightweight **file-based command / acknowledgment bridge**.

This project is **experimental** and intended as a proof-of-concept rather than a production-ready system.

---

## Project Status

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

##  Example Prompts

```text
set the tempo to 140 bpm
add a basic beat on track 1
what kick samples do I have?
insert a new track
remove track 2
