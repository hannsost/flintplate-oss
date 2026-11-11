"use client";

export const dynamic = "force-dynamic";

import { useParams } from "next/navigation";
import { RoomPage } from "@/components/interview-room/RoomPage";

export default function WorkerInterviewRoomPage() {
  const { scheduleId } = useParams<{ scheduleId: string }>();
  return (
    <RoomPage
      scheduleId={scheduleId}
      backUrl="/worker/interviews"
      isRecruiter={false}
    />
  );
}
