import { NextRequest, NextResponse } from "next/server";
export async function POST(request: NextRequest) {
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
    !origin ||
    !allowedOrigins.includes(origin) ||
    new URL(origin).host !== host
  ) {
    return NextResponse.json({ detail: "Invalid origin" }, { status: 403 });
  }
  const url = process.env.BACKEND_URL || "http://127.0.0.1:8000";
  try {
    const body = await request.text();
    if (body.length > 2000)
      return NextResponse.json(
        { detail: "Request too large" },
        { status: 413 },
      );
    const response = await fetch(new URL("/jobs", url), {
      method: "POST",
      cache: "no-store",
      signal: AbortSignal.timeout(55000),
      headers: {
        "Content-Type": "application/json",
        ...(process.env.BACKEND_API_TOKEN
          ? { Authorization: `Bearer ${process.env.BACKEND_API_TOKEN}` }
          : {}),
      },
      body,
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
