# Roadmap

## Near term

1. Run `python3 tools/harness.py native-resume` in a Rust/Cargo-capable environment.
2. Implement and verify G0-ACTOR, G0-WIRE, and G0-STORE against the checked-in public contracts/corpora.
3. Resolve G0-CRYPTO provider, trust, key-lifecycle, and migration decisions under security review.
4. Close the downstream L-WP01/L-WP02/L-WP03 integration path.

## Qualification

After native foundation closure, run the real platform/device, network, security, soak, recovery, migration, and release qualification campaigns required by the product plan. Local/reference PASS does not replace those campaigns.

## Public release

The final public release path also requires license/name/contact/repository/version decisions, final dependency/SBOM resolution, hosted CI, signing/attestation as selected, and explicit release authorization.
