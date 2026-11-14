import { NextRequest, NextResponse } from "next/server";
async function proxy(request: NextRequest) {
  // A shared backend token is not user authentication. Keep write proxy local-only
  // until owner authentication is implemented; hosted previews are read-only.
  if (process.env.NODE_ENV === "production") {
    return NextResponse.json(
      { detail: "Hosted write access awaits owner authentication" },
      { status: 403 },
    );
  }
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  const allowedOrigins = [
    `http://127.0.0.1:${request.nextUrl.port || "3000"}`,
    `http://localhost:${request.nextUrl.port || "3000"}`,
  ];
  if (
    request.method !== "GET" &&
    (!origin ||
      !allowedOrigins.includes(origin) ||
      new URL(origin).host !== host)
  ) {
    return NextResponse.json({ detail: "Invalid origin" }, { status: 403 });
  }
  const url = process.env.BACKEND_URL || "http://127.0.0.1:8000";
  try {
    const body = request.method === "GET" ? "" : await request.text();
    const path = request.nextUrl.searchParams.get("path") || "/jobs";
    if (
      !/^\/(platforms(?:\/(?:events|review))?|commands(?:\/[a-f0-9-]+(?:\/(?:plan|approve|run))?)?|reports(?:\/(?:settings|run|test|deliveries))?|finance|jobs(?:\/[a-f0-9-]+(?:\/(?:workflow|run|approval|reconcile|video))?)?|system(?:\/pause)?)$/.test(
        path,
      )
    )
      return NextResponse.json({ detail: "Invalid path" }, { status: 400 });
    if (body.length > 16384)
      return NextResponse.json(
        { detail: "Request too large" },
        { status: 413 },
      );
    const response = await fetch(new URL(path, url), {
      method: request.method,
      cache: "no-store",
      signal: AbortSignal.timeout(180000),
      headers: {
        "Content-Type": "application/json",
        ...(request.headers.get("idempotency-key")
          ? { "Idempotency-Key": request.headers.get("idempotency-key")! }
          : {}),
        ...(process.env.BACKEND_API_TOKEN
          ? { Authorization: `Bearer ${process.env.BACKEND_API_TOKEN}` }
          : {}),
      },
      body: body || undefined,
    });
    if (response.headers.get("content-type")?.includes("video/mp4"))
      return new NextResponse(response.body, {
        headers: { "Content-Type": "video/mp4" },
      });
    return NextResponse.json(await response.json(), {
      status: response.status,
    });
  } catch {
    return NextResponse.json(
      { detail: "Backend unavailable" },
      { status: 502 },
    );
  }
}

export const POST = proxy;
export const GET = proxy;
