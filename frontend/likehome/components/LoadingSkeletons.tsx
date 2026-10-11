import type { ReactNode } from "react";

function SkeletonBlock({ className }: { className: string }) {
  return <div aria-hidden="true" className={`animate-pulse rounded bg-slate-200 motion-reduce:animate-none ${className}`} />;
}

function LoadingFrame({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="status" aria-label={label} aria-busy="true" className="mt-6">
      {children}
    </div>
  );
}

export function PageLoadingSkeleton() {
  return (
    <LoadingFrame label="Loading page">
      <div className="mx-auto w-full max-w-7xl space-y-6 px-4 py-10 sm:px-6 lg:px-8">
        <SkeletonBlock className="h-4 w-28" />
        <SkeletonBlock className="h-9 w-2/3 max-w-xl" />
        <div className="grid gap-4 border-y border-slate-200 py-6 sm:grid-cols-2">
          <SkeletonBlock className="h-11 w-full" />
          <SkeletonBlock className="h-11 w-full" />
          <SkeletonBlock className="h-11 w-full" />
          <SkeletonBlock className="h-11 w-full" />
        </div>
      </div>
    </LoadingFrame>
  );
}

export function SessionLoadingSkeleton() {
  return (
    <LoadingFrame label="Checking your session">
      <div className="space-y-3">
        <SkeletonBlock className="h-5 w-40" />
        <SkeletonBlock className="h-4 w-64 max-w-full" />
      </div>
    </LoadingFrame>
  );
}

export function SearchResultsSkeleton() {
  return (
    <LoadingFrame label="Searching for stays">
      <div className="grid gap-4 md:grid-cols-2">
        {[0, 1, 2, 3].map((item) => (
          <div key={item} aria-hidden="true" className="rounded-lg border border-slate-200 bg-white p-4">
            <SkeletonBlock className="aspect-[16/9] w-full" />
            <SkeletonBlock className="mt-4 h-5 w-2/3" />
            <SkeletonBlock className="mt-3 h-4 w-1/3" />
            <SkeletonBlock className="mt-5 h-10 w-full" />
          </div>
        ))}
      </div>
    </LoadingFrame>
  );
}

export function BookingListSkeleton() {
  return (
    <LoadingFrame label="Loading your bookings">
      <div className="space-y-4">
        {[0, 1].map((item) => (
          <div key={item} aria-hidden="true" className="space-y-4 rounded-lg border border-slate-200 bg-white p-5">
            <SkeletonBlock className="h-6 w-1/2" />
            <SkeletonBlock className="h-4 w-1/3" />
            <div className="grid gap-3 sm:grid-cols-2">
              <SkeletonBlock className="h-10 w-full" />
              <SkeletonBlock className="h-10 w-full" />
              <SkeletonBlock className="h-10 w-full" />
              <SkeletonBlock className="h-10 w-full" />
            </div>
          </div>
        ))}
      </div>
    </LoadingFrame>
  );
}

export function BookingDetailsSkeleton() {
  return (
    <LoadingFrame label="Loading booking details">
      <div className="grid gap-3 sm:grid-cols-2">
        {[0, 1, 2, 3].map((item) => (
          <SkeletonBlock key={item} className="h-10 w-full" />
        ))}
      </div>
    </LoadingFrame>
  );
}

export function CheckoutSkeleton({ label = "Checking the current stay rate" }: { label?: string }) {
  return (
    <LoadingFrame label={label}>
      <div className="space-y-5">
        <SkeletonBlock className="h-6 w-48" />
        <div className="grid gap-4 rounded-lg border border-slate-200 bg-white p-5 sm:grid-cols-2">
          {[0, 1, 2, 3, 4, 5].map((item) => (
            <SkeletonBlock key={item} className="h-10 w-full" />
          ))}
        </div>
      </div>
    </LoadingFrame>
  );
}

export function PaymentSkeleton() {
  return (
    <LoadingFrame label="Loading payment">
      <div className="grid gap-4 rounded-lg border border-slate-200 bg-white p-5 sm:grid-cols-2">
        {[0, 1, 2, 3].map((item) => (
          <SkeletonBlock key={item} className="h-10 w-full" />
        ))}
      </div>
    </LoadingFrame>
  );
}