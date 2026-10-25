import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [directory, operationId, fixture] = process.argv.slice(2);
const bundle = resolve(directory);
const map = JSON.parse(await readFile(`${bundle}/sdk/sdk-map.json`, "utf8"));
const entry = map[operationId];
assert.equal(entry.httpMethod, "GET");
assert.ok(!entry.path.includes("{"));
const expected = JSON.parse(await readFile(fixture, "utf8"));
const { CloudflareApiClient } = await import(pathToFileURL(`${bundle}/compiled/index.js`).href);
const received = [];
const token = randomBytes(32).toString("hex");
const server = createServer((request, response) => {
  received.push({ method: request.method, url: request.url });
  if (request.method !== "GET" || request.url !== entry.path || request.headers.authorization !== `Bearer ${token}`) {
    response.writeHead(404).end();
    return;
  }
  response.writeHead(200, { "content-type": "application/json" });
  response.end(JSON.stringify(expected));
});
await new Promise((accept, reject) => {
  server.once("error", reject);
  server.listen(0, "127.0.0.1", accept);
});
try {
  const port = server.address().port;
  const client = new CloudflareApiClient({ baseUrl: `http://127.0.0.1:${port}`, token, maxRetries: 0, timeoutInSeconds: 3 });
  let owner = client;
  for (const segment of entry.accessor) owner = owner[segment];
  assert.equal(typeof owner[entry.method], "function");
  // This calls the generated method, not client.fetch or an injected fetcher.
  const actual = await owner[entry.method]();
  assert.deepEqual(actual, expected);
  assert.deepEqual(received, [{ method: "GET", url: entry.path }]);
  console.log(JSON.stringify({ status: "passed", check: "generated-sdk-mock-http", requests: received.length }));
} finally {
  server.closeAllConnections();
  await new Promise((accept) => server.close(accept));
}
