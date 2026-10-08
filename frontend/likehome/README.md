This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

The `/search` form validates dates and guest counts before submission. Check-in
can be today (the browser's local date) or later, check-out must be after
check-in, and guests must be an integer from 1 to 20. Missing or invalid inputs
show inline errors and prevent submission. Corrected inputs are validated again.

Start the FastAPI backend at `http://127.0.0.1:8000` to use live hotel search.
If it runs at another address, set `NEXT_PUBLIC_API_BASE_URL` in a local
`.env.local` file before starting the frontend. See `.env.example` for the
local default. Valid searches call `GET /hotels/search` and display the
returned properties; the browser does not call SerpApi directly.

### 4.7.2 Recent search replay

Valid search submissions save only the destination, dates, and guest count in
this browser's `localStorage` (`likehome_recent_searches_v1`). The five most
recent distinct searches are kept, newest first. Repeating the same search
moves it to the top; destination matching ignores case. Hotel results, prices,
and property tokens are never saved in this history. Clear history removes it.

The Search again button restores the form and makes a new `GET /hotels/search`
request with `no_cache=true`. Browser response caching is also disabled. The
backend forwards `no_cache=true` to SerpApi to request updated results instead
of its provider cache. Each replay uses SerpApi search quota. The loading,
empty-result, and retry states are shared with a normal search; retrying a
replay keeps the fresh-result setting. A new search resets filters and sorting.

Saved dates are validated again at replay time. An expired stay is restored
with inline errors so the user can correct it before a request is sent.
Malformed history entries are ignored. If browser storage is unavailable,
normal searches still work. Reloading the page loads history without making
an automatic hotel request. History is local to the browser, not an account.

The storage helpers in `lib/recent-searches.ts` and the `fresh` option on
`searchHotels` can also be used by the 4.7.1 recent-search UI.

### Result filters and sorting

After a search, maximum nightly price and amenity filters refine only the loaded
properties in the browser. The maximum is inclusive, uses `price_per_night` in
USD, and accepts nonnegative decimal amounts (including zero). A blank limit
shows all prices; invalid input shows an error and does not apply a price limit.
Missing prices remain visible without a limit and are excluded with a valid
limit. Amenity options come from the original loaded results, ignoring blank
values and duplicates after trimming whitespace and comparing case-insensitively.
A stay must contain **all** selected amenities as well as satisfy the price limit.
Counts refer to matching and loaded stays, not a global hotel total. Clear filters
restores the original results; a new search resets filters. Filter changes and
clearing make no API requests and consume no additional SerpApi quota.

The Sort stays select applies after filtering. Recommended / Default preserves
the API ordering; price can be sorted low to high or high to low, and guest
rating high to low. Missing prices or ratings appear last in their respective
sorts and are not hidden by sorting. Equal values retain their relative API
order. Sorting uses a copy and preserves the original hotel objects and search
context. Clear filters keeps the selected sort; a new search resets sorting to
Recommended / Default. Changing the sort makes no API or SerpApi requests.

Run the frontend tests with `npm test`, and run the lint check with
`npm run lint`. The tests use Node's built-in test runner and make no real API
requests.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
