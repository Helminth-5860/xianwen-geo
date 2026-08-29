import assert from "node:assert/strict";

import {
  publisherCapabilities,
  publisherHasVerifiedCapability,
  validateCapabilityConfiguration,
} from "./publishers/index.js";

const variables = [
  "PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS",
  "PUBLISHING_WORKER_VERIFIED_AUTH_PLATFORM_KEYS",
  "PUBLISHING_WORKER_VERIFIED_DRAFT_PLATFORM_KEYS",
  "PUBLISHING_WORKER_VERIFIED_PUBLIC_PLATFORM_KEYS",
  "PUBLISHING_WORKER_VERIFIED_IMAGE_PLATFORM_KEYS",
] as const;

const original = Object.fromEntries(variables.map((name) => [name, process.env[name]]));

try {
  for (const name of variables) delete process.env[name];
  validateCapabilityConfiguration();
  assert.ok(publisherCapabilities().every((item) => item.verified_capabilities.length === 0));
  assert.equal(publisherHasVerifiedCapability("zhihu", "public_publish"), false);

  process.env.PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS = "zhihu";
  process.env.PUBLISHING_WORKER_VERIFIED_AUTH_PLATFORM_KEYS = "zhihu";
  process.env.PUBLISHING_WORKER_VERIFIED_DRAFT_PLATFORM_KEYS = "zhihu";
  validateCapabilityConfiguration();
  const zhihu = publisherCapabilities().find((item) => item.platform_key === "zhihu");
  assert.deepEqual(zhihu?.verified_capabilities, ["auth", "draft"]);
  assert.ok(zhihu?.implemented_capabilities.includes("public_publish"));
  assert.equal(publisherHasVerifiedCapability("zhihu", "public_publish"), false);

  process.env.PUBLISHING_WORKER_VERIFIED_PUBLIC_PLATFORM_KEYS = "zhihu";
  validateCapabilityConfiguration();
  assert.equal(publisherHasVerifiedCapability("zhihu", "public_publish"), true);

  process.env.PUBLISHING_WORKER_VERIFIED_PUBLIC_PLATFORM_KEYS = "unknown-platform";
  assert.throws(() => validateCapabilityConfiguration(), /unsupported platform keys/);

  delete process.env.PUBLISHING_WORKER_VERIFIED_PUBLIC_PLATFORM_KEYS;
  process.env.PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS = "unknown-platform";
  assert.throws(() => validateCapabilityConfiguration(), /unsupported platform keys/);
} finally {
  for (const name of variables) {
    const value = original[name];
    if (typeof value === "string") process.env[name] = value;
    else delete process.env[name];
  }
}

console.log("publishing capability contract passed");
