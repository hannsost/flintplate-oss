"use client";

export const dynamic = "force-dynamic";

import { useParams } from "next/navigation";
import { RoomPage } from "@/components/interview-room/RoomPage";

export default function RecruiterInterviewRoomPage() {
  const { scheduleId } = useParams<{ scheduleId: string }>();
  return (
    <RoomPage
      scheduleId={scheduleId}
      backUrl="/dashboard/interviews"
      isRecruiter={true}
    />
  );
}
