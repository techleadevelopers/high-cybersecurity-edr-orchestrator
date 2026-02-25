# BlockRemote Backend Overview (Atualizado)

## Arquitetura
- FastAPI assíncrono; Redis TLS (`rediss://`, pool compartilhado); PostgreSQL via SQLAlchemy 2.x Async + Alembic; Celery usando Redis como broker/backend.
- Middlewares: SecurityHeaders; SubscriptionGuard (auth + paywall trial + rate limit por plano/adaptive); CORS opcional.
- Workers: `analyze_signal` (score + kill-switch) com análise stateful, métricas e circuito básico.
- Proto gRPC: `backend/proto/signals.proto`; servidor gRPC (`app/grpc_server.py`) expõe `SendHeartbeat` (gerar stubs antes de rodar).

## Autenticação, Tokens e Zero Trust
- Access JWT curto (15 min) com `sub`, `device_id`, `typ`, `jti`.
- Refresh rotativo: `/v1/auth/refresh`; armazenado em Redis `refresh:{user}:{device}:{jti}` (TTL 7d). `/v1/auth/logout` revoga refresh e opcionalmente publica bloqueio.
- Revogação imediata: flags Redis `revoked:device:{id}` ou `revoked:jti:{jti}` fazem `get_current_claims` retornar 403; SubscriptionGuard também bloqueia device revogado.
- Paywall trial 7 dias: `DeviceRegistration` registra created_at + attestation. `compute_paywall_state` (billing/status) combina subscription+registro; trial expirado ? 402. Attestation é obrigatória em novo device.

## Attestation de Hardware
- `DeviceRegistration` guarda `attestation_type`, `nonce`, `attested_public_key_hash`, `verified_at`, `risk_reason`.
- `/v1/billing/status` (POST) recebe `device_id` + attestation; sem attestation ? 403. `services/attestation.py` integra Play Integrity (API key) e App Attest (validator URL); fallback dev legacy.

## Billing
- Webhook HMAC `/v1/billing/webhook` (BILLING_WEBHOOK_SECRET); idempotência por `BillingEvent.event_id`.
- `/v1/billing/subscription` usa cache Redis (15 min) ou DB; escopado a user+device.
- `/v1/billing/status` retorna premium/trial, atualiza attestation; 402 se trial expirado.

## Sinais e Proteção
- `/v1/signals/heartbeat`: pipeline Redis (GET state + INCR/EXPIRE rate) numa viagem; se blocked ? 423. Valida admin/accessibility; se revogados ? revoke+block (403). Persiste Signal e últimas 10 leituras em `sig:{device}`.
- `/v1/security/trust-score`: retorna score de Redis, vinculado ao token/device.
- Kill-Switch WebSocket: token via `Sec-WebSocket-Protocol` ou `?token=`; `accept(compression=None)`; fecha 1008 inválido ou 4003 paywall. Envia `force_overlay` imediato se flag set.
- Kill-Switch Priority WS: `/v1/security/priority` para Android; ao receber `SYNTHETIC_TOUCH_ALARM` publica `CRITICAL_LOCK:{device}`.

## Engine de Score (stateful + Zero Trust)
- `SensorPayload` inclui `touch_event`, `motion_delta`, `device_admin_enabled`, `accessibility_enabled`, `platform`.
- SUSPECT_RAT: touch_event true + motion_delta < 0.05 penaliza score.
- Histórico: usa últimas 10 leituras para penalizar variação quase nula (automação).
- Circuit breaker: se fila Celery > 1000, reutiliza decisão anterior; métricas de latência em Redis (`metrics:celery:enqueue_ms`, `metrics:celery:runtime_ms`).
- Score < 50 ? AuditLog, revoke+block device, set `force_overlay`, publish kill-switch.

## EDR / Threat Intel
- Endpoint `/v1/edr/report` recebe apps suspeitos, permissões perigosas e DNS logs; cruza com blacklist de hashes/DNS/IP RAT.
- Threat scoring: sideloaded + SMS + Accessibility ? risco alto; contato com RAT ? risco crítico. Risco crítico dispara `IMMEDIATE_QUARANTINE`, revoga tokens e força overlay.

## Auditoria
- `/v1/audit/logs` (200 itens) filtra por user+device; índice `(user_id, device_id, created_at)`.
- AuditLog inclui user_id, device_id, threat_level, reason, signal_id, created_at (UTC).

## Redis
- Pool com timeouts curtos; TLS obrigatório fora de dev; usado em deps, guard, heartbeat, kill-switch (normal e priority), refresh, Celery, listas de sinais, métricas, flags de revogação/overlay.

## Config/Segurança
- Variáveis obrigatórias: DATABASE_URL, REDIS_URL, JWT_SECRET_KEY, BILLING_WEBHOOK_SECRET; DEBUG default False.
- Attestation: PLAY_INTEGRITY_API_KEY, APP_ATTEST_VALIDATOR_URL. gRPC: GRPC_PORT (default 50051).
- `.env*` ignorado (limpeza histórica pendente). Cabeçalhos: X-Content-Type-Options, X-Frame-Options DENY, X-XSS-Protection, HSTS 2 anos.

## Modelos
- Signal, AuditLog, Subscription, BillingEvent, DeviceRegistration (com attestation), Plan.

## Rate limiting
- trial 120/min; paid_basic 600/min; paid 1200/min; android_accessibility 1800/min (headers `X-Platform: android`, `X-Accessibility-Telemetry: true`). Chave `rl:{plan_tier}:{user}:{device}`.

## Operação e Observabilidade
- Alembic após mudanças de schema (attestation, novos campos de payload, índices).
- Redis na mesma AZ/região, TLS + AUTH; considere `notify-keyspace-events` para revogação.
- Logging estruturado (user_id, device_id, jti, decisão, latências) e OpenTelemetry em rotas críticas/worker.
- gRPC stubs: `python -m grpc_tools.protoc -I backend/proto --python_out=backend/app/grpc --grpc_python_out=backend/app/grpc backend/proto/signals.proto`.

## Backlog
- Ligar feeds reais de Threat Intel (hash/IP/domain) e gestão de blacklist.
- mTLS para gRPC e kill-switch priority em produção.
- Alerts usando métricas `metrics:celery:*` e eventos `CRITICAL_LOCK`/`IMMEDIATE_QUARANTINE`.
