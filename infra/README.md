# Infrastructure

Production runs the same Docker Compose stack as local development, on one Oracle Cloud
Always Free ARM server. Terraform creates the server and its network; GitHub Actions tests
every change and deploys `main` to the server.

```
GitHub push ─► CI (lint, tests on PostGIS, image build, terraform validate)
                 │ passes on main
                 ▼
               Deploy ─► rsync code over SSH ─► docker compose up --build on the server
                                                  ├─ db (Postgres + PostGIS)
                                                  ├─ redis
                                                  ├─ worker (polls Swiftly 24/7)
                                                  ├─ api
                                                  └─ web (Caddy: the map app, proxies /api and /ws)
```

## What Terraform creates (`terraform/`)

- A VCN with one public subnet, an internet gateway and a firewall that opens only SSH (22)
  and web ports (80, 443). Postgres, Redis and the API are never exposed.
- One `VM.Standard.A1.Flex` server (Ubuntu 24.04, ARM): 2 OCPUs, 12 GB RAM, 100 GB disk.
  First boot installs Docker and disables password SSH (`cloud-init.yaml`).
- Optionally, a $1 monthly budget that emails you if anything ever starts billing.

## First-time setup

1. **Oracle account.** Sign up at cloud.oracle.com. A card is required for verification.
   Choose your **home region** carefully: Always Free resources exist only there, and it can
   never be changed.
2. **API key for Terraform.** Console → Profile → My profile → API keys → Add API key →
   download the private key to `~/.oci/oci_api_key.pem`. The console then shows the tenancy
   OCID, user OCID, fingerprint and region.
3. **SSH key for the server:**
   ```sh
   ssh-keygen -t ed25519 -f ~/.ssh/ghostbus -C ghostbus-deploy
   ```
4. **Create the server.** `tf.sh` runs Terraform in Docker, so nothing else needs installing
   (on Windows, Application Control blocks the native OCI provider plugin):
   ```sh
   cd infra/terraform
   cp terraform.tfvars.example terraform.tfvars   # then fill it in
   ./tf.sh init
   ./tf.sh plan
   ./tf.sh apply
   ```
   If apply fails with **"Out of host capacity"**, Oracle has no free ARM servers in that
   availability domain right now. Try the others (`./tf.sh apply -var availability_domain=1`,
   then `2`) or retry later; capacity comes and goes.
5. **Turn on deploys.** In GitHub → Settings → Secrets and variables → Actions, add:

   | Kind | Name | Value |
   |---|---|---|
   | Variable | `DEPLOY_ENABLED` | `true` |
   | Secret | `DEPLOY_HOST` | output of `terraform output -raw public_ip` |
   | Secret | `DEPLOY_SSH_KEY` | contents of `~/.ssh/ghostbus` (the private key) |
   | Secret | `PROD_ENV` | the server's `.env`: your Swiftly key, a strong Postgres password (also inside `DATABASE_URL`), `PG_SHARED_BUFFERS=3GB` and `WEB_PORT=80` |

   Then run the **Deploy** workflow from the Actions tab, or push to `main`.

## Idle reclamation

Oracle may reclaim Always Free servers it considers idle over a 7-day window (low CPU,
network and memory use). This worker is light on CPU, so the stack sets Postgres's cache
(`PG_SHARED_BUFFERS=3GB`, the usual 25% of RAM) to keep memory use above that threshold.
Upgrading the account to Pay As You Go also exempts it from reclamation while Always Free
resources stay free; keep the budget alert on if you do.

## Terraform state

State is stored locally in `terraform/terraform.tfstate` (gitignored). Back it up: losing it
means Terraform no longer knows about the server. Moving it to Oracle Object Storage is a
good later improvement.
