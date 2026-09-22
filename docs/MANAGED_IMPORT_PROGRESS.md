# Managed import progress implementation note

The v2.1 managed-import progress contract is split intentionally between the import engine and API adapter:

- the engine reports phase-local completed source-file counts while staging and importing;
- the API adapter translates those counts into the additive monotonic whole-operation progress contract (`planning`, `staging`, `importing`, `finalizing`, `complete`);
- the final stdout API response remains unchanged.

This reconciles the original staging-count work from draft PR #163 with the monotonic contract merged in PR #167. The API adapter must not synthesize file completion counts when the engine already supplies them.
