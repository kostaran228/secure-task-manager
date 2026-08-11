const jsonHeaders = { "content-type": "application/json; charset=UTF-8" };

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: jsonHeaders });
}

function badRequest(message) {
  return json({ detail: message }, 400);
}

async function parseTask(request) {
  let payload;
  try {
    payload = await request.json();
  } catch {
    return { error: "Request body must be valid JSON" };
  }

  if (!payload || typeof payload.title !== "string") {
    return { error: "title is required" };
  }
  const title = payload.title.trim();
  if (title.length < 1 || title.length > 200) {
    return { error: "title must contain 1 to 200 characters" };
  }
  if (payload.description != null && (typeof payload.description !== "string" || payload.description.length > 1000)) {
    return { error: "description must be a string of up to 1000 characters" };
  }
  return { title, description: payload.description ?? null };
}

export async function handleRequest(request, env) {
  const url = new URL(request.url);

  if (request.method === "GET" && url.pathname === "/health") {
    return json({ status: "ok" });
  }

  if (request.method === "GET" && url.pathname === "/tasks") {
    const { results } = await env.DB.prepare(
      "SELECT id, title, description, created_at FROM tasks ORDER BY id DESC"
    ).all();
    return json(results);
  }

  if (request.method === "POST" && url.pathname === "/tasks") {
    const task = await parseTask(request);
    if (task.error) return badRequest(task.error);
    const result = await env.DB.prepare(
      "INSERT INTO tasks (title, description) VALUES (?, ?)"
    ).bind(task.title, task.description).run();
    const created = await env.DB.prepare(
      "SELECT id, title, description, created_at FROM tasks WHERE id = ?"
    ).bind(result.meta.last_row_id).first();
    return json(created, 201);
  }

  const taskMatch = url.pathname.match(/^\/tasks\/(\d+)$/);
  if (request.method === "GET" && taskMatch) {
    const task = await env.DB.prepare(
      "SELECT id, title, description, created_at FROM tasks WHERE id = ?"
    ).bind(Number(taskMatch[1])).first();
    return task ? json(task) : json({ detail: "Task not found" }, 404);
  }

  return json({ detail: "Not found" }, 404);
}

export default { fetch: handleRequest };
