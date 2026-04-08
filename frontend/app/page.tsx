type LatestGlucoseResponse = {
  status: string;
  data: {
    id: string;
    reading_timestamp: string;
    glucose_value: number;
    units: string;
    trend_direction: string | null;
    trend_description: string | null;
    trend_arrow: string | null;
    source: string;
    fetched_at: string;
    created_at: string;
  } | null;
  message?: string;
};

type SettingsResponse = {
  status: string;
  data: {
    id: string;
    low_red_max: number;
    low_yellow_max: number;
    green_min: number;
    green_max: number;
    high_yellow_max: number;
    default_graph_hours: number;
    units: string;
    time_format: string;
    created_at: string;
    updated_at: string;
  } | null;
};

type SyncStatusResponse = {
  status: string;
  data: {
    id: string;
    run_started_at: string;
    run_finished_at: string | null;
    status: string;
    readings_pulled: number;
    new_readings_saved: number;
    error_message: string | null;
    created_at: string;
  } | null;
  message?: string;
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;

async function fetchJson<T>(path: string): Promise<T | null> {
  if (!API_BASE_URL) {
    return null;
  }

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      cache: "no-store",
    });

    if (!response.ok) {
      return null;
    }

    return (await response.json()) as T;
  } catch {
    return null;
  }
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return date.toLocaleString();
}

export default async function Home() {
  const [latestGlucose, settings, syncStatus] = await Promise.all([
    fetchJson<LatestGlucoseResponse>("/glucose/latest"),
    fetchJson<SettingsResponse>("/settings"),
    fetchJson<SyncStatusResponse>("/sync-status"),
  ]);

  const latest = latestGlucose?.data ?? null;
  const settingsData = settings?.data ?? null;
  const sync = syncStatus?.data ?? null;

  return (
    <main className="min-h-screen bg-white text-black">
      <div className="mx-auto max-w-5xl px-6 py-10">
        <header className="mb-10">
          <p className="text-sm uppercase tracking-[0.2em] text-gray-500">
            Health Monitor App
          </p>
          <h1 className="mt-2 text-4xl font-bold tracking-tight">
            Dashboard
          </h1>
          <p className="mt-3 max-w-2xl text-gray-600">
            First live view of your Dexcom data pipeline through the worker,
            database, and backend API.
          </p>
        </header>

        {!API_BASE_URL && (
          <section className="mb-8 rounded-2xl border border-red-200 bg-red-50 p-5">
            <h2 className="text-lg font-semibold text-red-700">
              Missing frontend API setting
            </h2>
            <p className="mt-2 text-sm text-red-700">
              NEXT_PUBLIC_API_BASE_URL is not set in .env.local.
            </p>
          </section>
        )}

        <div className="grid gap-6 md:grid-cols-3">
          <section className="rounded-2xl border border-gray-200 p-6 shadow-sm">
            <p className="text-sm font-medium text-gray-500">Latest Glucose</p>

            {latest ? (
              <>
                <div className="mt-4 flex items-end gap-3">
                  <span className="text-5xl font-bold">
                    {latest.glucose_value}
                  </span>
                  <span className="pb-2 text-lg text-gray-500">
                    {latest.units}
                  </span>
                </div>

                <div className="mt-4 space-y-2 text-sm text-gray-700">
                  <p>
                    <span className="font-medium">Trend:</span>{" "}
                    {latest.trend_arrow ?? ""} {latest.trend_description ?? latest.trend_direction ?? "—"}
                  </p>
                  <p>
                    <span className="font-medium">Reading time:</span>{" "}
                    {formatDateTime(latest.reading_timestamp)}
                  </p>
                  <p>
                    <span className="font-medium">Fetched at:</span>{" "}
                    {formatDateTime(latest.fetched_at)}
                  </p>
                </div>
              </>
            ) : (
              <p className="mt-4 text-sm text-gray-600">
                No glucose reading available yet.
              </p>
            )}
          </section>

          <section className="rounded-2xl border border-gray-200 p-6 shadow-sm">
            <p className="text-sm font-medium text-gray-500">Latest Sync</p>

            {sync ? (
              <div className="mt-4 space-y-3 text-sm text-gray-700">
                <p>
                  <span className="font-medium">Status:</span> {sync.status}
                </p>
                <p>
                  <span className="font-medium">Readings pulled:</span>{" "}
                  {sync.readings_pulled}
                </p>
                <p>
                  <span className="font-medium">New readings saved:</span>{" "}
                  {sync.new_readings_saved}
                </p>
                <p>
                  <span className="font-medium">Started:</span>{" "}
                  {formatDateTime(sync.run_started_at)}
                </p>
                <p>
                  <span className="font-medium">Finished:</span>{" "}
                  {formatDateTime(sync.run_finished_at)}
                </p>
              </div>
            ) : (
              <p className="mt-4 text-sm text-gray-600">
                No sync status available yet.
              </p>
            )}
          </section>

          <section className="rounded-2xl border border-gray-200 p-6 shadow-sm">
            <p className="text-sm font-medium text-gray-500">Thresholds</p>

            {settingsData ? (
              <div className="mt-4 space-y-3 text-sm text-gray-700">
                <p>
                  <span className="font-medium">Low red max:</span>{" "}
                  {settingsData.low_red_max}
                </p>
                <p>
                  <span className="font-medium">Low yellow max:</span>{" "}
                  {settingsData.low_yellow_max}
                </p>
                <p>
                  <span className="font-medium">Green range:</span>{" "}
                  {settingsData.green_min}–{settingsData.green_max}
                </p>
                <p>
                  <span className="font-medium">High yellow max:</span>{" "}
                  {settingsData.high_yellow_max}
                </p>
                <p>
                  <span className="font-medium">Default graph hours:</span>{" "}
                  {settingsData.default_graph_hours}
                </p>
              </div>
            ) : (
              <p className="mt-4 text-sm text-gray-600">
                No settings data available yet.
              </p>
            )}
          </section>
        </div>

        <section className="mt-8 rounded-2xl border border-gray-200 p-6 shadow-sm">
          <h2 className="text-lg font-semibold">Current State</h2>
          <div className="mt-4 grid gap-3 text-sm text-gray-700 md:grid-cols-2">
            <p>
              <span className="font-medium">Frontend:</span> Connected locally
            </p>
            <p>
              <span className="font-medium">Backend:</span> FastAPI
            </p>
            <p>
              <span className="font-medium">Database:</span> Supabase Postgres
            </p>
            <p>
              <span className="font-medium">Worker:</span> Dexcom history-window sync
            </p>
          </div>
        </section>
      </div>
    </main>
  );
}