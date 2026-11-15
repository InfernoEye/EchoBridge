# EchoBridge privacy notes

- **Local inference:** Speech-to-text and installed text translation run locally after setup, provided all required components are available.
- **Downloads:** First-run setup contacts external distribution servers to download Whisper runtimes/models and offline translation packages.
- **Instant Capture:** When enabled, the microphone stream stays active while EchoBridge runs to minimize hotkey latency, but the app discards input samples while the recording hotkey is not held. Windows can show the mic as in use in this mode.
- **Hotkey audio:** Audio captured while holding the hotkey is processed for transcription; recordings are not intended to persist by default. An optional diagnostic save feature may retain audio when explicitly enabled.
- **Recent translations:** The app may store recently transcribed/translated text locally to support its history feature. Review this before speaking confidential information.
- **No account required:** EchoBridge does not require a user account or paid inference API to run locally.

Read the specific code and dependency licenses for details; this document describes the intended application behavior and is not an independent security audit.
