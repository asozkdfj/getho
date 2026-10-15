# @edge/contracts

`openapi.json` is exported from the FastAPI app and `src/generated/api.ts` is generated from it with
openapi-typescript. Do not edit either by hand. After changing API schemas, run `make contracts`.
CI (`make contracts-check`) fails on drift. `src/index.ts` re-exports friendly type names and shared enums
(checked against the backend by `apps/api/tests/test_contract_enums.py`).
