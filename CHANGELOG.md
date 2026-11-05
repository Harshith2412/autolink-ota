# Change history

## 1.0.0 — 2026-11-05

First complete vertical slice: ECU simulator, backend, dashboard, harness, fault matrix and documentation.

Defects found by testing during development, all fixed before the recorded evidence run:

- **Backend:** vehicle firmware version could stay stale when the last heartbeat was lost (found by the
  `packet_loss` scenario). The version is now derived from reliable STATE events (migration `0002`).
- **Dashboard:** `.deployments li` also matched the lifecycle rail's inner list items, making the page
  overflow horizontally; fixed with a child combinator, and the browser test now checks overflow at 1360 px and
  390 px.
- **Dashboard:** narrow-viewport overflow from `1fr` grid tracks; changed to `minmax(0, 1fr)`.
- **Harness:** disconnection fault not injected (`proxy={}` was falsy); kill scenario landing after completion;
  duplicate (hardware, version) in the wrong-hardware scenario. The first full matrix run (169/175, the 6 failures
  being that harness bug) is kept in `experiments/results/history/`.
- **Docs:** two Mermaid diagrams failed to parse (semicolons in labels); all diagrams are now validated with
  mermaid-cli.
- **Infrastructure:** invalid single-line HCL variable blocks in Terraform.
- **Dev setup:** a partial run could create accounts without saving their passwords; credentials are now saved
  per account and reruns are idempotent.
