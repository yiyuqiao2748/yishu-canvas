# NAS API Key Persistence

## Root Cause

The API settings page saves provider keys to:

```text
/app/API/.env
```

The NAS deployment already persisted `/app/data`, `/app/output`, and
`/app/assets/team-assets`, but it did not persist `/app/API`. Keys saved from
the browser were therefore stored inside the container filesystem and were lost
when the container was recreated during a Docker rebuild.

## Fixed Deployment Layout

`deploy/fnos/docker-compose.yml` must keep this bind mount:

```yaml
volumes:
  - ./data:/app/data
  - ./api-env:/app/API
  - ./team-assets:/app/assets/team-assets
  - ./output:/app/output
```

After this change, provider keys saved from the browser live on the NAS at:

```text
deploy/fnos/api-env/.env
```

Deployment-level secrets still live in:

```text
deploy/fnos/.env
```

## Source Sync Rule

When syncing code to NAS, never overwrite these runtime paths:

```text
deploy/fnos/.env
deploy/fnos/api-env/
deploy/fnos/data/
deploy/fnos/output/
deploy/fnos/team-assets/
```

Only source files should be copied during routine updates. Docker rebuilds can
replace the container, but these NAS-mounted paths must remain in place.
