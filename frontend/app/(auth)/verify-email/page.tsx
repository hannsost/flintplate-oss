"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { authApi } from "@/lib/api";

function VerifyEmailContent() {
  const params = useSearchParams();
  const token = params.get("token") ?? "";
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");

  useEffect(() => {
    if (!token) return;
    authApi
      .verifyEmail(token)
      .then(() => setStatus("success"))
      .catch(() => setStatus("error"));
  }, [token]);

  if (token && status === "loading") {
    return (
      <div className="flex justify-center py-8">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
      </div>
    );
  }

  if (status === "success") {
    return (
      <div className="rounded-lg bg-green-50 border border-green-200 p-4 text-sm text-green-700">
        <p className="font-medium">E-Mail-Adresse bestätigt!</p>
        <p className="mt-1">Dein Konto ist jetzt vollständig verifiziert.</p>
        <Link
          href="/login"
          className="mt-3 inline-block text-blue-600 hover:underline font-medium"
        >
          Zum Login
        </Link>
      </div>
    );
  }

  return (
    <div className="rounded-lg bg-red-50 border border-red-200 p-4 text-sm text-red-700">
      <p className="font-medium">Ungültiger oder abgelaufener Link.</p>
      <p className="mt-1">Bitte fordere erneut eine Bestätigungs-E-Mail an.</p>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="w-full max-w-md bg-white rounded-2xl shadow p-8">
        <h1 className="text-2xl font-bold mb-6 text-gray-900">E-Mail bestätigen</h1>

        <Suspense
          fallback={
            <div className="flex justify-center py-8">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
            </div>
          }
        >
          <VerifyEmailContent />
        </Suspense>

        <p className="mt-6 text-center text-sm text-gray-500">
          <Link href="/login" className="text-blue-600 hover:underline">
            Zurück zum Login
          </Link>
        </p>
      </div>
    </div>
  );
}
