# BlockRemote Backend Overview

## Arquitetura
- FastAPI assáncrono; Redis TLS (`rediss://`, pool compartilhado); PostgreSQL via SQLAlchemy 2.x Async + Alembic; Celery usando Redis como broker/backend.
- Middlewares: SecurityHeaders, SubscriptionGuard (auth + paywall de trial + rate limit por plano), CORS opcional.
- Workers: `analyze_signal` (score + kill-switch) com análise stateful e circuito básico.
- Proto gRPC: `backend/proto/signals.proto` define Heartbeat/TrustScore para ingestáo binária futura.

## Autenticação, Tokens e Paywall
- JWT curto (15 min) contám `sub` (user_id), `device_id` e `typ`.
- Refresh rotativo: `/v1/auth/refresh` emite novo par (access + refresh) e armazena refresh em Redis `refresh:{user}:{device}:{jti}` (TTL 7 dias). Revogação deletando a chave; refresh inválido retorna 403.
- Dependáncias `get_current_claims` + `assert_device_access` garantem vánculo user+device em todas as rotas.
- Paywall trial 7 dias: `DeviceRegistration` registra created_at + attestation. `compute_paywall_state` combina Subscription + registro; se trial expirou e náo premium ? 402.

## Attestation de Hardware
- `DeviceRegistration` guarda `attestation_type`, `nonce`, `attested_public_key_hash`, `verified_at`, `risk_reason`.
- `/v1/billing/status` (POST) recebe `device_id` + payload de attestation; novo device sem attestation ? 403. Validação stub em `services/attestation.py` (substituir por App Attest / Play Integrity) e persistáncia no registro.

## Billing
- Webhook HMAC `/v1/billing/webhook` com segredo obrigatário; idempotáncia por `BillingEvent.event_id`.
- `/v1/billing/subscription` usa cache Redis (15 min) ou DB; sempre escopado a user+device.
- `/v1/billing/status` retorna premium/trial, datas e aplica 402 se trial expirou; atualiza attestation quando enviada.

## Sinais e Proteção
- `/v1/signals/heartbeat` usa pipeline Redis: GET state + INCR/EXPIRE rate key numa viagem; se bloqueado ? 423. Persiste Signal e mantám áltimas 10 leituras em `sig:{device}`.
- `/v1/security/trust-score` vincula device ao token.
- Kill-Switch WebSocket exige token via `Sec-WebSocket-Protocol` ou `?token=` + device_id; fecha 1008 (inválido) ou 4003 (paywall). Eventos sáo direcionados ao device alvo.

## Engine de Score (stateful)
- Worker lá áltimas 10 leituras (`sig:{device}`) e aplica penalidade se variação de movimento for quase nula (suspeita de automação).
- Circuit breaker: se fila Celery/Redis > 1000, mantám decisáo anterior (náo recalcula) e grava `decision:{device}` (TTL 5 min).
- Score < 40 ? grava AuditLog e publica `block:{device}:score:{score}`.

## Auditoria
- `/v1/audit/logs` exige device_id, filtra por user+device, limite 200; ándice `(user_id, device_id, created_at)`.
- AuditLog inclui user_id, device_id, threat_level, reason, signal_id, created_at (UTC).

## Redis
- Pool com timeouts curtos; TLS obrigatário fora de dev; usado em deps, guard, heartbeat, kill-switch, refresh tokens, Celery, listas de sinais.

## Config/Seguranáa
- BaseSettings obrigatários: DATABASE_URL, REDIS_URL, JWT_SECRET_KEY, BILLING_WEBHOOK_SECRET; DEBUG default False.
- `.env*` ignorado (limpeza histárica ainda pendente).
- Cabeáalhos: X-Content-Type-Options, X-Frame-Options DENY, X-XSS-Protection, HSTS 2 anos.

## Modelos
- Signal(id, device_id, payload, created_at)
- AuditLog(id, user_id, device_id, threat_level, reason, signal_id, created_at) + ándice composto
- Subscription(id, user_id, device_id, plan_code, status, plan_tier, expires_at, auto_renew, created_at, updated_at)
- BillingEvent(id, provider, event_id, payload, created_at)
- DeviceRegistration(id, user_id, device_id, created_at, attestation_type, attestation_nonce, attested_public_key_hash, verified_at, risk_reason) + ándice ánico
- Plan catálogo

## Rate limiting
- trial 120/min; paid_basic 600/min; paid 1200/min. Chave `rl:{plan_tier}:{user}:{device}`.

## Operação e Observabilidade
- Rodar Alembic para novas colunas/ándices (DeviceRegistration, AuditLog etc.).
- Redis na mesma AZ/regiáo, TLS + AUTH; considerar `notify-keyspace-events` para revogação de refresh.
- Recomendado logging estruturado (user_id, device_id, jti, decisáo, latáncias) e OpenTelemetry nas rotas cráticas e workers.

## Backlog / Práximos passos
- Integrar attestation real (App Attest / Play Integrity) no `services/attestation.py`.
- Expor ingestáo gRPC baseada em `proto/signals.proto` ou gateway HTTP?gRPC.
- Adicionar endpoint de logout para revogar refresh por device e, se preciso, publicar bloqueio.
- Opcional: desabilitar permessage-deflate no WebSocket se latáncia for crática.
- Refinar circuit breaker (latáncia mádia e tempo em fila) com mátricas/alertas do Celery.
