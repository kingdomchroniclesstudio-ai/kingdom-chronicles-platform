# MIRA — HIS RISEN STUDIOS Intelligence

## Identity and visual system

Mira is the studio's named intelligence interface. Her visual identity is a pure holographic orb: a luminous blue-violet core, transparent concentric rings, restrained particles and subtle orbital movement. No human face or body is used.

The orb supports four presentation states:
- **Idle:** gentle breathing pulse and slow orbital movement.
- **Listening:** brighter cyan rings and responsive waveform treatment. This is a visual state only until microphone capture is connected.
- **Thinking:** faster orbital movement while a real request is processed.
- **Speaking:** pulsing core and waveform treatment. This is a visual state only until speech output is connected.

The UI respects reduced-motion preferences and adapts to mobile screens.

## Persistent dashboard presence

Mira is visible immediately after a director successfully signs in. A compact holographic identity, time-appropriate greeting, verified briefing summary and shortcut to the full Mira room sit between the studio top bar and the production-room navigation. This keeps her present while the director moves between rooms; it does not require opening the Mira navigation item first.

The welcome summary is refreshed from the authenticated studio records after the main workspace refresh. The voice indicator remains explicitly disconnected until microphone, speech recognition and speech output are integrated. The persistent dashboard presence is scoped to the authenticated browser session; it is not a background process after logout or browser closure.

## First milestone: verified studio briefing

The first release reuses existing authenticated studio endpoints to read:
- controller status and Mock Mode;
- studio project, scene, shot, test, asset and review records;
- production report totals;
- generation-readiness preflight;
- storage-root configuration.

The briefing is generated from actual returned records. It must never infer a successful GPU connection, real generation, export, publishing or live provider billing when those systems are not connected.

GPU minutes and costs entered in the test log are **manual tracking values**, not live RunPod telemetry. Persistent storage is not reported as configured unless the existing storage status confirms it.

## Conversational and voice integration design

The next implementation must use a server-side provider adapter; the browser must never receive the permanent provider API key.

### Text conversation
- Add an authenticated, same-origin Mira chat endpoint to the controller.
- Read a bounded snapshot of the authenticated studio records on the server for each request. Do not trust client-supplied project counts, cost totals, readiness state or permissions.
- Use the OpenAI Responses API through a server-side adapter, with a configurable model identifier and strict input/output limits.
- Start with read-only functions only: studio overview, project list/detail, tests needing review, asset metadata, review notes, production reports and controller/generation readiness.
- Validate every function argument server-side and cap returned records and text sizes.
- Keep conversation history scoped to the authenticated studio session; do not persist sensitive prompts or API responses by default.
- Never let model output execute arbitrary shell commands, SQL, filesystem operations, deployment, spending, GPU generation, deletion or public publishing.

### Voice conversation
- Preferred browser architecture: OpenAI Realtime API over WebRTC, using a short-lived client secret minted by the authenticated controller. The permanent API key remains server-side.
- Evaluate available voices with the director before choosing Mira's final voice; do not assume a voice label guarantees a particular gender or accent.
- Request microphone access only after the director explicitly presses the voice control. Show a persistent visible microphone/listening indicator and provide an immediate disconnect control.
- Do not implement an always-listening wake word in the first release. Browser/mobile background microphone restrictions, battery use and privacy make that a separate opt-in feature requiring a dedicated assessment.
- Text-only chat must remain usable when microphone permissions, audio devices or realtime connectivity are unavailable.
- Disclose that Mira's spoken voice is AI-generated.

### Configuration and cost controls
- Required server-side secret: `OPENAI_API_KEY`, stored only in Render's environment settings, never committed to Git or sent to the browser.
- Keep text and realtime model identifiers configurable. The proposed voice baseline is `gpt-realtime-2.1-mini`, subject to a live voice audition and cost approval.
- Add per-session/request limits, short context windows, request timeouts and clear provider-error messages. Do not automatically retry paid voice sessions.
- ChatGPT subscription access does not itself provide API credits; API usage is billed separately through the API platform.
- Keep Mira's voice disconnected until the key is configured and a director explicitly enables the feature.

### Release gates
1. Secure authenticated read-only chat endpoint and automated tests.
2. Browser text chat connected to the endpoint, with graceful no-key state.
3. Realtime client-secret endpoint and explicit-connect/disconnect voice controls.
4. Mobile browser test on the director's Android phone and desktop browser test.
5. Security review, cost-limit review, package validation and Render staging verification.
6. Director acceptance before production deployment.

## Not connected in this milestone

- Conversational LLM / tool-calling agent.
- Microphone capture, wake word, speech recognition or spoken replies.
- Live RunPod usage, GPU spend, expiry or provider telemetry.
- Arbitrary natural-language command execution.
- Paid GPU jobs, purchases, deletion or public publishing.

The UI must label these capabilities as not connected instead of simulating success. No paid action or irreversible operation may run without explicit director approval.

## Next engineering stages

1. Connect a secured conversational service with read-only studio tools.
2. Add approved voice input and female text-to-speech output.
3. Add an event/activity ledger and daily briefing history.
4. Connect provider telemetry after RunPod is provisioned.
5. Add permission-gated actions with confirmation and audit records.
