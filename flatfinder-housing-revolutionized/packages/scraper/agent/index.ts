import { Agent, callable, routeAgentRequest } from "agents";

type ScraperState = {
  isRunning: boolean;
  lastRunAt: string | null;
  totalListingsFound: number;
  regions: string[];
};

export class ListingScraperAgent extends Agent<Env, ScraperState> {
  initialState: ScraperState = {
    isRunning: false,
    lastRunAt: null,
    totalListingsFound: 0,
    regions: ["london", "manchester", "birmingham"],
  };

  // ── Scheduling controls ──────────────────────────────────────────────────

  @callable()
  async start(intervalSeconds = 600) {
    await this.scheduleEvery(intervalSeconds, "run-scrape-cycle");
    this.setState({ ...this.state, isRunning: true });
    return { status: "started", intervalSeconds };
  }

  @callable()
  async stop() {
    await this.cancelSchedule("run-scrape-cycle");
    this.setState({ ...this.state, isRunning: false });
    return { status: "stopped" };
  }

  @callable()
  async runNow() {
    return this.runScrapeCycle();
  }

  @callable()
  async setRegions(regions: string[]) {
    this.setState({ ...this.state, regions });
    return { regions };
  }

  // ── Scheduled handler ────────────────────────────────────────────────────

  async onScheduledEvent(_: ScheduledEvent, payload: string) {
    if (payload === "run-scrape-cycle") {
      await this.runScrapeCycle();
    }
  }

  // ── Core loop — calls Python service ─────────────────────────────────────

  private async runScrapeCycle() {
    const results = await Promise.all(
      this.state.regions.map((region) => this.scrapeRegion(region))
    );

    const totalFound = results.reduce((sum, r) => sum + r.listingsFound, 0);

    this.setState({
      ...this.state,
      lastRunAt: new Date().toISOString(),
      totalListingsFound: this.state.totalListingsFound + totalFound,
    });

    return { regions: results, totalFound };
  }

  private async scrapeRegion(region: string) {
    const serviceUrl = this.env.SCRAPER_SERVICE_URL;

    const res = await fetch(`${serviceUrl}/scrape/${region}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });

    if (!res.ok) {
      console.error(`Scrape failed for ${region}: ${res.status}`);
      return { region, listingsFound: 0, error: res.statusText };
    }

    const data = (await res.json()) as { listings_found: number };
    return { region, listingsFound: data.listings_found };
  }
}

// ── Cloudflare Worker entry ──────────────────────────────────────────────────

export default {
  fetch: (req: Request, env: Env) =>
    routeAgentRequest(req, env) ??
    new Response("Not found", { status: 404 }),
};

// ── Env bindings ─────────────────────────────────────────────────────────────

interface Env {
  ListingScraperAgent: DurableObjectNamespace;
  SCRAPER_SERVICE_URL: string; // e.g. https://scraper.your-domain.com
}
