import test from "node:test";
import assert from "node:assert/strict";
import { handleRequest } from "../src/index.js";

class FakeDatabase {
  constructor() { this.tasks = []; }
  prepare(sql) {
    const db = this;
    return {
      bind(...values) {
        return {
          async run() {
            const task = { id: db.tasks.length + 1, title: values[0], description: values[1], created_at: "2026-08-11 00:00:00" };
            db.tasks.push(task);
            return { meta: { last_row_id: task.id } };
          },
          async first() { return db.tasks.find((task) => task.id === values[0]) ?? null; }
        };
      },
      async all() { return { results: [...db.tasks].reverse() }; }
    };
  }
}

const env = { DB: new FakeDatabase() };

test("health endpoint is public", async () => {
  const response = await handleRequest(new Request("https://example.workers.dev/health"), env);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { status: "ok" });
});

test("tasks can be created and listed", async () => {
  const create = await handleRequest(new Request("https://example.workers.dev/tasks", {
    method: "POST", body: JSON.stringify({ title: "Deploy edge API" })
  }), env);
  assert.equal(create.status, 201);
  assert.equal((await create.json()).title, "Deploy edge API");

  const list = await handleRequest(new Request("https://example.workers.dev/tasks"), env);
  assert.equal(list.status, 200);
  assert.equal((await list.json()).length, 1);
});
