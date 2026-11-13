import type { Metadata } from "next";

export const metadata: Metadata = {
    title: "My bookings | LikeHome",
};

export default function rewardPage() {
    return (
        <section className="border-b-2 border-slate-200 mx-auto w-full max-w-7xl px-4 py-10 sm:px-6 sm:py-14 lg:px-8">
            <p className="text-sm font-semibold text-teal-700">Your account</p>
            <div className="border-solid border-3 rounded border-teal-700 bg-slate-100 Grid grid-col-1 grid-flow-row text-center">
                <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">
                    Total Points:
                </h1>
                <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">
                    777
                </h1>
            </div>
        </section>
    );
}