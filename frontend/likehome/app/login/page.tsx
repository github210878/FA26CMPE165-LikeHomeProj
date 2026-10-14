import type { Metadata } from "next";
import AccountLayout from "@/components/AccountLayout";
import LoginForm from "@/components/LoginForm";
import { safeCheckoutReturnTo } from "@/lib/checkout-selection";

export const metadata: Metadata = {
  title: "Sign in | LikeHome",
};

export default async function LoginPage({ searchParams }: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const returnTo = safeCheckoutReturnTo((await searchParams).next);
  return (
    <AccountLayout title="Welcome back" description="Sign in to plan your next stay or pick up where you left off.">
      <LoginForm returnTo={returnTo} />
    </AccountLayout>
  );
}
