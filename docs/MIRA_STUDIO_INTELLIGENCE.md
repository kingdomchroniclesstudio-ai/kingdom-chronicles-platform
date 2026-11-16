# MIRA — HIS RISEN STUDIOS Intelligence

## Identity and visual system

Mira is the studio's named intelligence interface. Her visual identity is a pure holographic orb: a luminous blue-violet core, transparent concentric rings, restrained particles and subtle orbital movement. No human face or body is used.

The orb supports four presentation states:
- **Idle:** gentle breathing pulse and slow orbital movement.
- **Listening:** brighter cyan rings and responsive waveform treatment while a user-started, one-utterance browser speech-recognition session is active.
- **Thinking:** faster orbital movement while a real Gemini request is processed.
- **Speaking:** pulsing core and waveform treatment while the browser's device speech-synthesis API reads a reply aloud.

These states are connected to the on-demand browser voice/chat lifecycle where the relevant APIs are supported. They do not indicate an always-listening microphone or a background wake-word service. The UI respects reduced-motion preferences and adapts to mobile screens.

## Persistent dashboard presence

Mira is visible immediately after a director successfully signs in. A compact holographic identity, time-appropriate greeting, verified briefing summary and shortcut to the full Mira room sit between the studio top bar and the production-room navigation. This keeps her present while the director moves between rooms; it does not require opening the Mira navigation item first.

The welcome summary is refreshed from the authenticated studio records after the main workspace refresh. The voice indicator reports **VOICE READY · ON DEMAND** when the browser provides speech recognition. Voice use still requires the Gemini data-use acknowledgement, separate microphone consent and an explicit click on **Talk to Mira**. This indicator does not mean the microphone is always active or that a wake-word/background companion is installed. The persistent dashboard presence is scoped to the authenticated browser session; it is not a background process after logout or browser closure.

## First milestone: verified studio briefing

The first release reuses existing authenticated studio endpoints to read:
- controller status and Mock Mode;
- studio project, scene, shot, test, asset and review records;
- production report totals;
- generation-readiness preflight;
- storage-root configuration.

The briefing is generated from actual returned records. It must never infer a successful GPU connection, real generation, export, publishing or live provider billing when those systems are not connected.

GPU minutes and costs entered in the test log are **manual tracking values**, not live RunPod telemetry. Persistent storage is not reported as configured unless the existing storage status confirms it.

## Conversational AI — Gemini free-tier text assistant

The first conversational provider is Google Gemini, using the current stable low-cost model code **gemini-3.8-flash**. The controller calls Google's recommended Interactions API from the server. Each request sets `store=false` and sends bounded client-side chat history, avoiding server-side Interaction record retention and retrieval. No browser-side SDK or permanent provider key is used.

- Required server-side secret: **GEMINI_API_KEY**, stored only in Render environment settings. Never commit it or send it in chat.
- Required separate operator acknowledgement: **MIRA_GEMINI_FREE_TIER_ACK=true**. Set it only after verifying that the Google AI Studio project is on the Free tier and has no Cloud Billing linked. The application cannot query or independently verify the project's billing tier.
- The model is fixed to **gemini-3.8-flash** in this milestone; there is no browser-side model override or paid-provider fallback.
- Short studio questions use the documented low thinking level to reduce latency; the server request timeout is 45 seconds and provider timeouts/HTTP failures are surfaced as distinct, actionable messages. No automatic paid-provider or model fallback is attempted.
- No paid-tier upgrade, billing activation or automatic paid fallback is part of this implementation. A key tied to a paid Google Cloud billing project may incur charges; the acknowledgement flag is an operator guard, not a technical billing lock.
- The service uses bounded messages, at most eight recent conversation turns, a short request timeout, a per-session rate limit and a capped answer length.
- Up to eight recent turns are resent with the current message on each request. Google documents that its Unpaid Services may use submitted content and generated responses to improve products and may allow human reviewers to read, annotate or process inputs and outputs. `store=false` stops the API from retaining retrievable Interaction objects; it does not opt out of the Unpaid Services data-use terms.
- Recent conversation steps are held only in controller process memory, keyed by a hash of the authenticated Director session token. They are cleared on logout and expire after one hour of inactivity; they are not written to the studio database.
- Google requests use the Interactions API with `store=false`. This prevents Google from retaining a retrievable Interaction record, but does not opt out of Google's free-tier data-use terms or possible human review.
- The server builds its own trusted, aggregate snapshot for each request. Client-supplied studio counts and permissions are ignored.
- The aggregate snapshot includes only controller mode, total project/scene/shot/test/asset/review counts, status counts and whether a persistent data root is configured.
- The snapshot excludes project titles, screenplay text, generation prompts, asset names or notes, review comments and cost entries. Mira must say when the information she is asked for is not in that snapshot.
- Gemini is given no function tools. Model output cannot invoke SQL, shell commands, filesystem access, GPU jobs, spending, deployment, deletion, take approval or publishing.
- The /api/mira/chat route requires the authenticated Director session, a same-origin browser request and explicit acknowledgement of the free-tier data-use notice.

### Gemini free-tier privacy notice

Google's current pricing documentation identifies eligible free-tier model input and output as free of charge, and states that free-tier content may be used to improve Google's products. Google's Gemini API Additional Terms also say that human reviewers may read, annotate and process submitted inputs and generated outputs for Unpaid Services. The app displays this notice before enabling chat. The director's message and up to eight recent turns are sent to Google on each request, so do not type confidential scripts, unreleased prompts, credentials, personal details or sensitive production information into Mira. Limiting the automatic studio snapshot reduces exposure but does not change Google's free-tier data-use terms.

The API key must belong to a Google AI Studio Free-tier project with no active Cloud Billing linked. A project with active Cloud Billing is treated as a Paid Service and may incur charges. The application cannot check this status. The separate `MIRA_GEMINI_FREE_TIER_ACK=true` environment setting is an operator acknowledgement, not an enforceable billing cap or proof that the project is free. Do not set it until the project has been checked in Google AI Studio.

### Voice

- On-demand microphone input uses the browser's Web Speech API speech-recognition interface where available. The director must acknowledge a separate microphone-privacy notice and press **Talk to Mira** for each one-utterance session; a visible Stop Listening control ends capture. No wake word, continuous background listening or microphone permission request is used before the director activates voice.
- The browser/platform recognition service may process microphone audio, often through an online service. Mira's Render server receives the recognized transcript, not a raw audio recording; the transcript is sent to Gemini with the same aggregate snapshot and free-tier data-use terms as typed text.
- Spoken replies use the device's Web Speech API speech synthesis and locally available voices. The UI lets the director choose from available device voices and prefers a voice with a common feminine name when one is installed, but the platform does not expose reliable gender metadata and the actual sound varies by device. No external paid TTS service is connected.
- Speech recognition support, language accuracy, microphone permission and available voices vary across browsers/devices. Text chat remains available as the fallback.
- Logging out or withdrawing voice consent aborts any active recognition session and stops device speech output.
- The assistant remains read-only and uses the same verified aggregate studio snapshot for typed and spoken questions. Voice changes how the director communicates; it does not grant Mira additional studio data access or command permissions.

### Deployed release status — 16 November 2026

- The Mira foundation (PR #13) and on-demand voice/latency update (PR #14) are merged into `main` and deployed to the Render Director Console.
- GitHub Actions run **43382192132** completed successfully on 13 November 2026. The package validation job passed ZIP identity/integrity, package extraction/layout, Python dependency installation, Mira browser-JavaScript syntax validation, all **112 regression tests**, controller startup and local health smoke tests, updater probes, and the live Render health/entry-page checks.
- Render reported the voice-enabled deployment as live. The API key remains server-side and is not exposed to the browser or stored in this document.
- The director confirmed one successful authenticated desktop voice smoke test after deployment: microphone input, browser transcription, Gemini response and spoken device reply all worked.
- That successful smoke test does not establish compatibility with every browser/device or cover denied microphone permission, no-speech, network failure and Android cases. Those acceptance checks remain pending.
- The deployed voice release is still **on demand**. It does not include a Windows background companion, wake-word detector or continuous microphone listening.

## Not connected in this milestone

- A Windows desktop companion that starts with Windows, stays in the system tray and detects a local wake phrase such as “Hey Mira”.
- Always-on or continuous background microphone capture. The current studio voice interface listens only after the director explicitly clicks **Talk to Mira**, and captures one utterance per session.
- Android voice compatibility and the full set of microphone-denied, no-speech, offline/network and device-voice acceptance tests.
- A hosted/paid neural voice service.
- Live RunPod usage, GPU spend, expiry or provider telemetry.
- Arbitrary natural-language command execution.
- Paid GPU jobs, purchases, deletion or public publishing.

The UI must label these capabilities as not connected instead of simulating success. No paid action or irreversible operation may run without explicit director approval.

## Next engineering stages

1. Complete a fresh authenticated studio acceptance pass for text chat and on-demand voice, including microphone denial, no-speech, Stop Listening, logout cleanup and network failure.
2. Build the Windows companion as a separate local application. Keep wake-word detection on the PC, require a visible microphone status and provide immediate mute/pause/quit controls. Do not stream idle microphone audio to Gemini.
3. Test Android compatibility separately; do not assume desktop browser behavior transfers to Android.
4. Consider controlled retrieval of individual project/scene records only with explicit director opt-in, data minimization and a renewed privacy review. Do not send confidential scripts or unreleased prompts to the Gemini Free tier by default.
5. Add an event/activity ledger and daily briefing history.
6. Connect provider telemetry after RunPod is provisioned.
7. Keep any future studio actions permission-gated, separately confirmed and audit-logged. Mira remains read-only in the current release.
