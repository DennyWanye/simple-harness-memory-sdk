# Integration status

Status as of 2026-08-22 for `simple-harness-memory-sdk` 0.4.0:

| Consumer | Interface status | Product integration / testing |
|---|---|---|
| `simple_harness` | Exact-wheel candidate interface ready | S6 product cutover and MCP-driven real UI testing are pending; this document does not claim completion early. |
| AIPhone | Agent Memory v1 interface ready | Not integrated, modified or tested in this Program. |
| K6/AgentOS | Agent Memory v1 interface ready | Not integrated, modified or tested in this Program. Existing product data is untouched. |
| NovelTagSystem | Outside this integration | Not modified, migrated or tested. |

The SDK conformance boundary covers trusted deployment/household/actor/session identity, personal/family
scope, automatic recall and committed-turn delivery. It does not claim product-specific authentication,
deployment, database migration, UI behavior or cross-device synchronization for future consumers.
