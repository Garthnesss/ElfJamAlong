# Research notes — May to November 2026

Compiled 2026-11-11 from web searches and the pages linked below. "Checked" means the page itself was read; "search only" means only a search summary was seen. Nothing here was tested by us unless it says so.

## What changes our plan

### 1. Ableton Link Audio (Live 12.4, released May 2026) — likely replaces the tap
- Link now carries **audio** as well as tempo: apps "announce and discover audio channels and exchange audio aligned to the shared musical timeline". It works over localhost, so Live and another app on the same Mac can exchange audio. (README checked: https://github.com/Ableton/link; launch coverage, search only: https://cdm.link/ableton-live-12-4-adds-link-audio-updated-effects-hands-on-details/)
- The installed Live here is **12.4.16**, so it is available now. Enable at Settings → Link → Link Audio.
- SDK: C++17, header-only, `LinkAudio.hpp` in the same repo. No Python bindings mentioned. **Licence: GPLv2+ or a proprietary licence from Ableton** — the same constraint as Link itself.
- **Not verified:** whether Live can send one *track* (the guitar) rather than the master, and the latency. Ableton's FAQ returned 403 to the fetcher. Check in Live's UI first: https://help.ableton.com/hc/en-us/articles/25425913328924-Link-Audio-FAQ
- **Why it matters:** if a single track can be sent, ElfJamAlong gets the guitar alone, sample-aligned to the beat, with none of its own notes in the signal. That removes the own-note problem and the macOS-only tap in one move. It would need a small C++ helper (like `livetap`) that receives a Link Audio channel and pipes PCM to Python.

### 2. Magenta RealTime 2 (Google, 4 June 2026) — the nearest thing to a competitor
- Open weights, runs locally on Apple Silicon, ships an **AUv3 plugin** and a standalone app. Steered by text, audio and **MIDI**: hold a chord and it generates a band following that harmony. Control latency about 200 ms. (Repo checked earlier: https://github.com/magenta/magenta-realtime; coverage, search only: https://officechai.com/ai/google-releases-magenta-realtime-2-for-on-device-live-music-synthesis/)
- Sizes: 230M parameters (any Apple Silicon Mac) and 2.4B (Pro/Max chips). Weights CC BY 4.0 plus Google terms.
- **It outputs audio, not MIDI, and takes MIDI chords, not a guitar.** ElfJamAlong's difference: it listens to a real instrument, and what it plays is editable MIDI on the user's own instruments.
- **Idea worth trying:** ElfJamAlong's detected chords could drive MRT2 as a sound source. Chord detection → MIDI chord → MRT2 band. Not tried.

### 3. StreamMUSE — "Real-Time Language Model Jamming" (arXiv 2606.11886, June 2026)
- Symbolic, real time. The human plays a **melody**; a 0.12B-parameter transformer generates the **accompaniment** — the mirror image of ElfJamAlong. Checked (abstract and most of the HTML): https://arxiv.org/abs/2606.11886
- Useful design points: one tick = a sixteenth note (same grid as ours); strictly causal; it generates **further ahead than the inference interval**, so a late result still has notes to play. That overlap trick is how to run a model that is slower than one step.
- Trained on POP909. Says "open source"; only a project page was found, no licence seen.

### 4. LK Jam (arXiv 2606.21018, June 2026) — call and response in a VST3
- GRU model inside a **JUCE VST3 plugin**, inference with **RTNeural**, synced to host tempo. The human plays a phrase, the AI answers with one ("trading fours"). Checked: https://arxiv.org/abs/2606.21018 — code: https://github.com/yakunliu-aimusic/LK_Jam (not read, licence unknown).
- No measured latency or listening results in the paper; it states expectations only.
- Relevant to ROADMAP M5 (call and response) and M6 (plugin): a working example of a small recurrent model in a real plugin.

### 5. LiveBand (arXiv 2606.03803, June 2026, Sony CSL) — audio accompaniment
- Listens to a live **audio** mix and generates an accompanying instrument as audio. ~150M-parameter causal transformer; 30–80 ms per ~93 ms frame on an RTX 3090. Checked: https://arxiv.org/abs/2606.03803
- The transferable idea is **anticipation**: predict the frame slightly ahead of what has been heard, so output is on time despite compute delay. Our ROADMAP M3 (know the loop) is the symbolic version of this.

### 6. Logic Pro 12 (January 2026) and 12.3 (June 2026)
- **Chord ID** analyses a recorded audio or MIDI region and writes its chords to the Chord Track; Session Players then follow. 12.3 improved its accuracy. Search only: https://synthanatomy.com/2026/06/apple-logic-pro-12.html
- Still works on **recorded regions**, not live input, as far as the coverage shows. So Logic does not do what ElfJamAlong does, but Logic users already have "chords from my recording → a band".

## Added 2026-11-12

- **Link Audio API, read from `LinkAudio.hpp`.** Construct `LinkAudio(bpm, peerName)`, call `enableLinkAudio(true)`, list senders with `channels()` (each has `id`, `name`, `peerName`; `setChannelsChangedCallback` reports changes), and subscribe with `LinkAudioSource(link, channelId, callback)`. The callback gets interleaved 16-bit samples with `numChannels`, `numFrames`, `sampleRate`, and the session beat time of the buffer. Ableton's example app is `LinkAudioHut` (CMake, in `examples/`). A receiver helper for ElfJamAlong is therefore small: pick a channel by name, mix to mono, write float32 to stdout. https://github.com/Ableton/link
- **Per-track sending from Live is still unconfirmed.** CDM's hands-on says Note and Move "let you select individual tracks for Link Audio as well as the main mix" and that Live has a Link Audio page in Settings; it does not say what Live itself can send. Still needs a look in Live 12.4. https://cdm.link/ableton-live-12-4-adds-link-audio-updated-effects-hands-on-details/
- **Void-LinkAudio** (Julien Bayle): open-source Link Audio for Max, Pure Data, TouchDesigner, VCV Rack and openFrameworks, with VST/AU/CLAP plug-ins distributed separately; validated against Live 12.4. GPL-2.0-or-later. No command-line receiver, but its openFrameworks receive example is a second reference. One note there: a 44.1 kHz receiver against a 48 kHz sender dropped about 8% of audio, so a receiver should run at the sender's rate. https://github.com/gluon/Void-LinkAudio
- **No Python bindings for Link Audio** were found (one search). A Rust port of Link with a Link Audio example exists: https://github.com/anweiss/ableton-link-rs (not read).
- **POP909 is MIT-licensed**: the repository's LICENSE file reads "MIT License, Copyright (c) 2020 Music X Lab". That covers the dataset files; the songs themselves are commercial pop, so for a sold product this is weaker than it looks. Its chord and key labels were partly made by algorithm. https://github.com/music-x-lab/POP909-Dataset
- **Chord recognition:** a DAFx 2026 paper uses pseudo-labelling and distillation to improve rare chord qualities and mentions low-latency DAW use (search summary only): https://www.dafx.de/paper-archive/2026/papers/DAFx26_paper_22.pdf. Pseudo-labelling unlabelled guitar audio with a large offline model is a way round our shortage of varied training data. No new paper on causal guitar chord recognition was found.
- **Our own finding:** GuitarSet's 15 progressions are shared by all players, so any model input longer than about a chord's length learns the progressions and scores well for the wrong reason. Details in STATUS.md.

## Background that did not change in this period
- **No shipping product was found** that listens to a live guitar and plays MIDI accompaniment in a DAW. Closest: ReChord (MIDI-keyboard arranger, rule-based), Chordify/Moises (analyse files). One search, not exhaustive: https://gearspace.com/threads/rechord-a-vst-software-arranger-with-real-time-auto-accompaniment.1374965/
- **Real-time chord recognition:** no new paper found for guitar. One hobby project reports 0.31 s strum-to-chord with a CNN on log-mel input, close to our 0.3 s. Search only: https://github.com/Breakdown08/chordfinder
- **Chord-conditioned melody generation:** "Chord-conditioned Melody and Bass Generation" (arXiv 2511.08755, NeurIPS 2025 workshop) found that predicting the **bass first, then the melody** worked best of five orderings. Trained on TAVERN (Mozart and Beethoven variations). Checked: https://arxiv.org/abs/2511.08755
- **Running models inside plugins:** RTNeural (small, audio-thread safe, limited layer types) and anira (moves ONNX/LibTorch/TFLite inference off the audio thread; https://arxiv.org/abs/2506.12665). A DAFx 2026 paper benchmarks these on Apple Silicon under DAW load; the PDF could not be read, so its conclusions are unknown: https://www.dafx.de/paper-archive/2026/papers/DAFx26_paper_16.pdf

## Training data for the melody model — licences still to check
None of these were confirmed. Each needs its own licence read before use, and before any sale.

| Dataset | What it has | Status |
|---|---|---|
| POP909 | 909 pop songs: melody, accompaniment, chords, key | MIT (repository LICENSE, read 2026-11-12); underlying songs are commercial pop |
| Hooktheory / TheoryTab lead sheets | ~11k melody + chord snippets | scraped from a commercial site; assume not usable commercially |
| EWLD / Wikifonia | ~5k lead sheets | copyrighted songs; unclear |
| TAVERN | classical variations with harmony labels | licence not seen; wrong style for guitar jams |
| GuitarSet | already used for chords; also has solo melodies over the same progressions | CC BY 4.0, confirmed |

GuitarSet's **solo** excerpts are melodies a guitarist improvised over the same chord charts as the comping excerpts. That is small (about 90 minutes) but licence-clean and exactly on topic; it is the obvious first dataset for ROADMAP M4.

## Easy to miss
1. **Latency is a budget, not a number.** Detection ≈ 0.3 s, model inference, MIDI and instrument latency all add up. Both StreamMUSE and LiveBand solve it by generating ahead; nobody solves it by being fast enough.
2. **Evaluate on unseen players.** Our own first GuitarSet number was inflated until players were held out. Keep that rule for the melody model too.
3. **GPL reaches further than Link.** Link Audio is under the same licence. A sold product needs Ableton's proprietary licence or a plugin that takes audio and tempo from the host.
4. **A plugin removes three problems at once:** the tap, own-note handling and Link. That is the strongest argument for doing ROADMAP M6 earlier than its number suggests.
5. **MRT2 moves fast.** Version 1 was June 2025, version 2 June 2026. If Google adds live audio input, the overlap with ElfJamAlong grows; the MIDI-out, editable, capture-to-clip side is where it does not compete.
