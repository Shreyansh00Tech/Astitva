"use client";

import { AgentReviewQueue } from "@/components/agent-review";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { useSession } from "@/lib/session";
import { Lock } from "lucide-react";

export default function AgentReviewPage() {
  const { can, loading } = useSession();
  if (!loading && !can("risk:decide")) return <EmptyState icon={Lock} title="Security Manager only" description="Agent review is visible to the Security Manager. Managers see the final score on each request." />;
  return (
    <>
      <PageHeader title="Agent Review" description="Five review agents next to the rule engine. When their score and the rule score disagree, you set the final score of record." />
      <AgentReviewQueue />
    </>
  );
}
