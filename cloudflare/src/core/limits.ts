// Cloudflare-specific safety ceiling: the Workers FREE plan allows only 50
// external subrequests per Workflow *instance* (the whole multi-step audit
// run shares one budget, it is not reset per step - see Cloudflare's
// Workflows limits docs). Every external fetch anywhere in the pipeline
// (crawl, broken-link checks, DNS-over-HTTPS MX lookups, PageSpeed) must go
// through this so a single audit can never blow the budget and get the
// whole Workflow instance killed by the platform.
//
// The paid plan raises this to 10,000 by default, so this ceiling is
// deliberately conservative rather than plan-aware: it costs nothing to stay
// under it even on a paid account, and it keeps behaviour identical on both.
export class SubrequestBudget {
  private remaining: number;
  readonly startedWith: number;

  constructor(total = 40) {
    this.remaining = total;
    this.startedWith = total;
  }

  get left(): number {
    return this.remaining;
  }

  take(n = 1): boolean {
    if (this.remaining < n) return false;
    this.remaining -= n;
    return true;
  }
}
