#!/usr/bin/env node
/**
 * join 门禁：以 contract/openapi.json（前端契约快照）为真实后端 openapi 的子集做核对。
 *
 * 用法：node scripts/contract-check.mjs [baseUrl]
 * 前置：后端已在 baseUrl 运行（默认 http://127.0.0.1:8000），
 *       且 FIRST_ADMIN_USERNAME/PASSWORD 与启动后端时一致（可用同名环境变量覆盖）。
 *
 * 三道断言：
 *   1. 快照中的每个 path + method 真实后端必须存在；
 *   2. 快照每个 schema 的 properties/required 是真实同名 schema 的子集；
 *   3. 真实登录 → /me smoke。
 * 任一项漂移：非零退出并打印差异。
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const base = process.argv[2] ?? "http://127.0.0.1:8000";

const snapshot = JSON.parse(
  await readFile(path.join(root, "contract", "openapi.json"), "utf8"),
);

function deref(node, schemas, seen = new Set()) {
  let props = {};
  const required = [];
  if (!node || typeof node !== "object" || seen.has(node)) return { props, required };
  seen.add(node);
  if (node.$ref) {
    return deref(schemas[node.$ref.split("/").pop()], schemas, seen);
  }
  Object.assign(props, node.properties ?? {});
  required.push(...(node.required ?? []));
  for (const part of node.allOf ?? []) {
    const nested = deref(part, schemas, seen);
    props = { ...props, ...nested.props };
    required.push(...nested.required);
  }
  return { props, required: [...new Set(required)] };
}

async function fail(message) {
  console.error(`✗ ${message}`);
  process.exitCode = 1;
  throw new assert.AssertionError({ message });
}

// --- 拉取真实契约 ---
let live;
try {
  const response = await fetch(`${base}/openapi.json`);
  assert.equal(response.status, 200);
  live = await response.json();
} catch (error) {
  await fail(`无法获取 ${base}/openapi.json，请确认后端已启动并合并计划②：${String(error)}`);
}

// --- 1. paths/methods 子集 ---
const pathDrift = [];
for (const [route, operations] of Object.entries(snapshot.paths)) {
  if (!live.paths[route]) {
    pathDrift.push(`缺少路径 ${route}`);
    continue;
  }
  for (const method of Object.keys(operations)) {
    if (!live.paths[route][method]) {
      pathDrift.push(`缺少方法 ${method.toUpperCase()} ${route}`);
    }
  }
}
if (pathDrift.length > 0) {
  await fail(`契约路径漂移：\n${pathDrift.map((line) => `  - ${line}`).join("\n")}`);
}
console.log("✓ paths/methods：快照全部存在于真实后端");

// --- 2. schema 字段与 required 子集 ---
const liveSchemas = live.components?.schemas ?? {};
const snapshotSchemas = snapshot.components.schemas;
const missingSchemas = [];
const propertyDrift = [];
const requiredDrift = [];

for (const [name, schema] of Object.entries(snapshotSchemas)) {
  const liveSchema = liveSchemas[name];
  if (!liveSchema) {
    missingSchemas.push(name);
    continue;
  }
  const expected = deref(schema, snapshotSchemas);
  const actual = deref(liveSchema, liveSchemas);
  for (const key of Object.keys(expected.props)) {
    if (!(key in actual.props)) propertyDrift.push(`${name}.${key}`);
  }
  const actualRequired = new Set(actual.required);
  for (const key of expected.required) {
    if (!actualRequired.has(key)) requiredDrift.push(`${name}:${key}`);
  }
}

if (missingSchemas.length > 0) {
  await fail(`真实文档缺少 schema：${missingSchemas.join(", ")}`);
}
if (propertyDrift.length > 0) {
  await fail(`真实响应缺少快照字段：${propertyDrift.join(", ")}`);
}
if (requiredDrift.length > 0) {
  await fail(`真实 required 约束相对快照收缩：${requiredDrift.join(", ")}`);
}
console.log("✓ schemas：字段与 required 约束均为真实后端的子集");

// --- 3. 登录 → /me smoke ---
const username = process.env.FIRST_ADMIN_USERNAME ?? "cc_admin";
const password = process.env.FIRST_ADMIN_PASSWORD ?? "Cc#contract-2026";

const loginResponse = await fetch(`${base}/api/v1/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ username, password }),
});
if (loginResponse.status !== 200) {
  await fail(`登录 smoke 失败：HTTP ${loginResponse.status} ${await loginResponse.text()}`);
}
const tokenBody = await loginResponse.json();
if (!tokenBody.access_token || typeof tokenBody.role !== "string") {
  await fail("登录响应缺少 access_token/role");
}

const meResponse = await fetch(`${base}/api/v1/auth/me`, {
  headers: { Authorization: `Bearer ${tokenBody.access_token}` },
});
if (meResponse.status !== 200) {
  await fail(`/me smoke 失败：HTTP ${meResponse.status}`);
}
const me = await meResponse.json();
if (me.username !== username) {
  await fail(`/me 返回用户名不一致：期望 ${username}，实际 ${me.username}`);
}
console.log("✓ login → /me smoke 通过");
console.log("契约核对全部通过。");
