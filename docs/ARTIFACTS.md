# Code and artifacts

This repository is the lightweight code distribution. The companion archive is
`gpt54-camera-ready-20261104-results-v2.zip`; it holds1545 selected trial traces and14558
trace/config/retrieval/verifier files, with original and release hashes.

Archive SHA256:
`1a86da6e8a4898e324ac3c14ec08d12364d5d91d314f8f2c3be538eddb1c3e20`

A public download URL/DOI has not been assigned. Add the actual versioned URL
once published; do not substitute a made-up repository or DOI. The private raw
staging archive is NOT part of this code release.

The selected numeric files are also included here so table reproduction works
without downloading traces or calling a provider. `scripts/reproduce_table.py
--check` compares all45 metrics. Runtime is agent seconds; Tokens is input tokens
including cached input, not input+output and not total campaign expenditure.

The full container filesystem is not available for411 migrated TB2 records.
Their action traces and result records exist; most native artifacts directories
only contain manifests. See the companion detailed report for these limits.
