"use client";
import { use } from "react";
import { RequestDetail } from "@/components/request-detail";
export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <RequestDetail id={id} backHref="/requests" backLabel="Access requests" />;
}
