#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
terraform fmt -check -recursive infra
terraform -chdir=infra/environments/dev init -backend=false -input=false -lockfile=readonly
terraform -chdir=infra/environments/dev validate
# Every provider in these tests is mocked; no Azure login or resources are used.
terraform -chdir=infra/environments/dev test
