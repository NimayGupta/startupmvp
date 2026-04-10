# Discount Function (Rust/WASM)

**Phase:** 4A

This directory contains the Shopify Function that applies A/B experiment discounts
at checkout, running inside Shopify's infrastructure as a WebAssembly module.

## Why a Shopify Function?

Shopify Functions run inside Shopify's infrastructure at checkout, meaning:
- Zero external API call latency at purchase time
- No dependency on our servers being available during checkout
- Discounts are applied atomically with the cart

## How it works

1. The Checkout UI Extension (Phase 4B) assigns each visitor to a `control` or `treatment`
   group and writes a cart attribute `ab_group: "control" | "treatment"`.
2. This Rust function reads that cart attribute.
3. If `ab_group == "treatment"`, it applies the discount percentage stored in the
   experiment configuration metafield.
4. If `ab_group == "control"` or the attribute is absent, no discount is applied.

## Setup (Phase 4A)

```bash
# Create the function from the Shopify CLI template
shopify app function create \
  --name discount-ab-test \
  --type product_discounts \
  --language rust

# Run function tests
cargo test

# Deploy
shopify app function deploy
```

## Current state

This directory is a **stub** created in Phase 1 to reserve the directory structure.
The Rust implementation will be written in Phase 4A.
