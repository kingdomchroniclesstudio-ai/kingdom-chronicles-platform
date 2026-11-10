# MIRA — HIS RISEN STUDIOS Intelligence

## Identity and visual system

Mira is the studio's named intelligence interface. Her visual identity is a pure holographic orb: a luminous blue-violet core, transparent concentric rings, restrained particles and subtle orbital movement. No human face or body is used.

The orb supports four presentation states:
- **Idle:** gentle breathing pulse and slow orbital movement.
- **Listening:** brighter cyan rings and responsive waveform treatment. This is a visual state only until microphone capture is connected.
- **Thinking:** faster orbital movement while a real request is processed.
- **Speaking:** pulsing core and waveform treatment. This is a visual state only until speech output is connected.

The UI respects reduced-motion preferences and adapts to mobile screens.

## First milestone: verified studio briefing

The first release reuses existing authenticated studio endpoints to read:
- controller status and Mock Mode;
- studio project, scene, shot, test, asset and review records;
- production report totals;
- generation-readiness preflight;
- storage-root configuration.

The briefing is generated from actual returned records. It must never infer a successful GPU connection, real generation, export, publishing or live provider billing when those systems are not connected.

GPU minutes and costs entered in the test log are **manual tracking values**, not live RunPod telemetry. Persistent storage is not reported as configured unless the existing storage status confirms it.

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
