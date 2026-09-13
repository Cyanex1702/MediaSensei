# Acquire images from a prompt or manual plan

Create a project whose policy allows external data, then build a plan. Planning does not access the network.

```bash
mediasensei project create "Marine life" --data-policy approved_external
mediasensei acquire prompt PROJECT_ID "Get 500 usable marine-life images, including sharks and turtles, minimum 1024px"
mediasensei acquire plan PROJECT_ID --topic "marine life" --target 500 --category sharks --category turtles --min-width 1024 --min-height 1024
```

Inspect the returned plan, provider list, generated queries, estimates, relevance mode, and budgets. Test a small sample or authorize the full run explicitly:

```bash
mediasensei acquire test PLAN_ID --count 20 --allow-remote
mediasensei acquire run PLAN_ID --allow-remote
mediasensei worker run
mediasensei acquire status RUN_ID
mediasensei acquire candidates RUN_ID --state rejected --reason low_resolution
```

`--allow-remote` is required for each new run and does not override a `local_only` project. The default production discovery adapters are Wikimedia Commons and Openverse; `direct-url` accepts explicit HTTP(S) image URLs in manual queries. Production downloads require HTTPS and public destinations. Provider credentials, when a future provider needs them, must remain outside the plan, provenance, and error records.

The run stops when it reaches the accepted-asset target or a safety/provider boundary. `completed_with_shortfall` is a successful, inspectable terminal result with fewer accepted assets than requested; read `stop_reason`, rejection counts, and failed candidates. Pausing checkpoints between candidates. Resuming does not re-download accepted assets. Review candidates stay quarantined until an explicit `accept` or `reject` decision:

```bash
mediasensei acquire decide CANDIDATE_ID accept
mediasensei acquire control RUN_ID pause
mediasensei acquire control RUN_ID resume
mediasensei acquire control RUN_ID cancel
```

The Acquisition dashboard provides the same prompt/manual planning, plan review, test/start authorization, progress, yield, safety controls, and rejection reporting workflow.