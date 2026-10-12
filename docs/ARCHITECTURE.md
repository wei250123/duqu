# Duqu Gateway Architecture

Duqu is an edge gateway for collecting industrial telemetry, processing it
locally, and publishing it to MQTT. The project is organized by responsibility
so the desktop UI is only one client of the runtime.

## Runtime flow

```text
main.py
  -> GatewayRuntime
      -> Database maintenance
      -> GatewayApiServer (optional local management API)
      -> DeviceManager
          -> Collector -> Communication/Protocol
          -> Processor -> MQTT publisher
      -> CacheManager (offline retry queue)
```

`GatewayRuntime` owns start and stop ordering. This keeps the same background
services available to a future headless entry point or Windows service without
copying lifecycle code from the Qt application.

## Module boundaries

| Area | Responsibility | Depends on |
| --- | --- | --- |
| `config/` | Dataclasses, loading, persistence, migration | filesystem, security encryption for secrets |
| `core/runtime/` | Process lifecycle and service orchestration | API, storage, device manager |
| `core/api/` | Read-only health, status, Prometheus endpoints, and static Web monitor | runtime providers, standard library HTTP |
| `device/` | Device configuration and runtime state | collector, MQTT, storage, auth |
| `core/collector/` | Scheduling and collecting device points | communication and protocols |
| `core/communication/` | Serial and Ethernet transports | protocol implementations |
| `core/protocols/` | Modbus and custom frame parsing | communication interfaces |
| `core/processor/` | Filtering, conversion, aggregation, and transformation | data models, configuration |
| `core/mqtt/` | MQTT connection, reconnect, backup broker, publish | cache manager, configuration |
| `core/storage/` | SQLite records and offline upload queue | configuration, logger |
| `core/security/` | Authentication, authorization, encryption, audit | configuration, logger |
| `ui/` | PyQt6 views and user interaction | device manager, auth, runtime state |
| `utils/` | Logging, watchdog, and cross-cutting helpers | standard library |

## Dependency rules

1. UI code calls managers and services; it does not own worker threads or
   database connections.
2. Protocol and transport modules do not import PyQt6.
3. Storage modules do not call UI widgets.
4. Configuration dataclasses are the boundary for persisted settings.
5. New background workers must be started and stopped by `GatewayRuntime`.
6. New API endpoints must be read-only until an explicit authorization and
   audit design is added.

## Extension guide

- Add a new industrial protocol under `core/protocols/` and register it in the
  protocol factory.
- Add a new data processing stage under `core/processor/` and connect it to the
  pipeline configuration.
- Add a device capability in `device/` without putting protocol details in UI
  pages.
- Add operational health data through a provider passed to
  `GatewayApiServer`, rather than importing UI state into the API.

## Entry points

- `python main.py`: Qt desktop application plus optional local API.
- `GatewayRuntime`: reusable lifecycle object for a future headless runner.
- `/healthz`, `/readyz`, `/api/v1/status`, `/metrics`: monitoring endpoints.
