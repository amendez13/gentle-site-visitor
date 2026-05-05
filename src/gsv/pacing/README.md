# gsv.pacing

The pacing layer turns browser primitives into named, composable controls for
visit execution. It follows the composition rule in `docs/ARCHITECTURE.md`
section 4.3: a runner checks cancellation, acquires the rate limiter, executes a
step, waits for optional content, applies a delay profile, ticks the burst
governor, then checks cancellation again.

## Built-in Profiles

| Name | Range | Distraction |
| --- | --- | --- |
| `production` | 2.0-5.0s | 10% chance of 15.0-45.0s |
| `recon` | 0.8-1.8s | none |
| `auth` | 0.5-1.0s | none |
| `disabled` | 0.0s | none |

Custom profiles are registered in `visitor.pacing.profiles` and selected with
`visitor.pacing.profile`. Missing fields inherit an existing profile of the same
name when overriding one, or default to zero values for a new profile.
