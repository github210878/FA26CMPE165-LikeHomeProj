import type { ComponentProps } from "react";
import ReservationChangeForm from "@/components/ReservationChangeForm";

export default function ReservationChangeFlow(props: ComponentProps<typeof ReservationChangeForm>) {
  return <ReservationChangeForm {...props} />;
}
