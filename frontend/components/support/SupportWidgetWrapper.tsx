"use client";

import { useEffect, useState } from "react";
import { auth } from "@/lib/auth";
import { authApi } from "@/lib/api";
import { SupportWidget } from "./SupportWidget";

/** Only renders the SupportWidget for recruiter/admin users. */
export function SupportWidgetWrapper() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) return;
    authApi.me(token)
      .then((u) => { if (u.role === "recruiter" || u.role === "admin") setShow(true); })
      .catch(() => {});
  }, []);

  if (!show) return null;
  return <SupportWidget />;
}
