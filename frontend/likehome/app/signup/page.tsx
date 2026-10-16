import type { Metadata } from "next";
import AccountLayout from "@/components/AccountLayout";
import SignupForm from "@/components/SignupForm";

export const metadata: Metadata = {
  title: "Sign up | LikeHome",
};

export default function SignupPage() {
  return (
    <AccountLayout title="Sign up for LikeHome" description="Your next getaway starts here. Enter your details to create an account." signup>
      <SignupForm />
    </AccountLayout>
  );
}
